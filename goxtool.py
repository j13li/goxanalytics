#!/usr/bin/env python2

"""
Backend daemon for retrieval and storage of live trade and depth data 
from MtGox as well as supplying the data to the GoxAnalytics frontend
"""
#  Copyright (c) 2013 Jiazheng Li
#  Based on original work (c) 2013 Bernd Kreuss <prof7bit@gmail.com>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.

# pylint: disable=C0301,C0302,R0902,R0903,R0912,R0913,R0914,R0915,R0922,W0703

import argparse
import goxapi
import logging
import locale
import math
import os
import sys
import time
import traceback
import threading
try:
    import pymysql
except ImportError:
    import MySQLdb

sys_out = sys.stdout #pylint: disable=C0103
import tornado.web
import tornado.websocket
import tornado.ioloop
import datetime
            
dbcon = None
config = goxapi.GoxConfig("goxtool.ini")
gox = None

class CustomWebSocketHandler(tornado.websocket.WebSocketHandler):
    def __init__(self, application, request):
        tornado.websocket.WebSocketHandler.__init__(self, application, request)
        if(application.gox):
            self.gox = application.gox
            self.gox.clients.append(self)
            
    def on_message(self, message):

        print "Got message: %s" % message    
        cur = try_get_cursor(dbcon, config)
        t_start = time.time()
        if message == "Price":
            cur.execute("SELECT MAX(date), SUM(price * volume) / SUM(volume) \
                        FROM Trades \
                        WHERE date < (unix_timestamp() - 3600 * 24) \
                        GROUP BY DATE(FROM_UNIXTIME(date)), HOUR(from_unixtime(date)) \
                        UNION \
                        SELECT date, SUM(price * volume) / SUM(volume) \
                        FROM Trades WHERE date >= (UNIX_TIMESTAMP() - 3600 * 24) \
                        GROUP BY date;")
            price = { "key": "Price", "values": [] }
            price["values"] = [list(r) for r in cur.fetchall()]
            data = { "key": "Price", "values": [price] }
            self.write_message(data)
        if message == "Volume":
            askvol = { "key": "askvol", "values": [] }
            bidvol = { "key": "bidvol", "values": [] }
            cur.execute("SELECT MAX(date), SUM(volume) \
                        FROM Trades \
                        WHERE type = 'ask' \
                            AND date < (unix_timestamp() - 3600 * 24) \
                        GROUP BY date(from_unixtime(date)), hour(from_unixtime(date))\
                        UNION \
                        SELECT date, SUM(volume) \
                        FROM Trades \
                        WHERE date >= (unix_timestamp() - 3600 * 24) \
                            AND type = 'ask' \
                        GROUP BY date;")
            askvol["values"] = [list(r) for r in cur.fetchall()]
            cur.execute("SELECT MAX(date), SUM(volume) \
                        FROM Trades \
                        WHERE type = 'bid' \
                            AND date < (unix_timestamp() - 3600 * 24) \
                        GROUP BY date(from_unixtime(date)), hour(from_unixtime(date)) \
                        UNION \
                        SELECT date, SUM(volume) \
                        FROM Trades \
                        WHERE date >= (unix_timestamp() - 3600 * 24) \
                            AND type = 'bid' \
                        GROUP BY date;")
            bidvol["values"] = [list(r) for r in cur.fetchall()]
            data = { "key": "Volume", "values": [askvol, bidvol] }
            self.write_message(data)
        if message == "OBVol":
            cur = try_get_cursor(dbcon, config)
            cur.execute("SELECT MAX(date), AVG(bid_usd / ask_btc / price), \
                            AVG(bid_usd_bandpass / ask_btc_bandpass / price), \
                            AVG(bid_usd_exp / ask_btc_exp / price), \
                            AVG(bid_usd_linear / ask_btc_linear / price) \
                        FROM OBVol \
                        WHERE date < (UNIX_TIMESTAMP() - 3600 * 24) \
                        GROUP BY date(from_unixtime(date)), hour(from_unixtime(date)) \
                        UNION \
                        SELECT date, AVG(bid_usd / ask_btc / price),  \
                            AVG(bid_usd_bandpass / ask_btc_bandpass / price), \
                            AVG(bid_usd_exp / ask_btc_exp / price), \
                            AVG(bid_usd_linear / ask_btc_linear / price) \
                        FROM OBVol \
                        WHERE date >= (UNIX_TIMESTAMP() - 3600 * 24) \
                        GROUP BY date;")
            OBVol = { "key": "OBVol", "values": [list(r) for r in cur.fetchall()] }
            self.write_message(OBVol)
            
        print ("%s call done in %f seconds" % (message, time.time() - t_start))

application = tornado.web.Application([(r"/websocket", CustomWebSocketHandler),])


def try_get_cursor(dbcon, config):
    try:
        cur = dbcon.cursor()
        return cur
    except:
        if ("pymysql" in sys.modules):
            dbcon = pymysql.connect(config.get("db", "hostname", "localhost"), 
                            config.get("db", "username", ""), 
                            config.get("db", "password", ""), 
                            config.get("db", "database", ""))
        elif ("MySQLdb" in sys.modules):
            dbcon = MySQLdb.connect(config.get("db", "hostname", "localhost"), 
                            config.get("db", "username", ""), 
                            config.get("db", "password", ""), 
                            config.get("db", "database", ""))
        else:
            dbcon = None
        cur = dbcon.cursor()
        return cur



HEIGHT_STATUS   = 2
HEIGHT_CON      = 7
WIDTH_ORDERBOOK = 80

INI_DEFAULTS =  [["goxtool", "set_xterm_title", "True"]
                ,["goxtool", "dont_truncate_logfile", "False"]
                ,["goxtool", "show_orderbook_stats", "True"]
                ,["goxtool", "highlight_changes", "True"]
                ,["goxtool", "orderbook_group", "0"]
                ,["goxtool", "orderbook_sum_total", "False"]
                ,["goxtool", "display_right", "history_chart"]
                ,["goxtool", "depth_chart_group", "1"]
                ,["goxtool", "depth_chart_sum_total", "True"]
                ,["goxtool", "show_ticker", "True"]
                ,["goxtool", "show_depth", "True"]
                ,["goxtool", "show_trade", "True"]
                ,["goxtool", "show_trade_own", "True"]
                ]


def dump_all_stacks():
    """dump a stack trace for all running threads for debugging purpose"""

    def get_name(thread_id):
        """return the human readable name that was assigned to a thread"""
        for thread in threading.enumerate():
            if thread.ident == thread_id:
                return thread.name

    ret = "\n# Full stack trace of all running threads:\n"
    #pylint: disable=W0212
    for thread_id, stack in sys._current_frames().items():
        ret += "\n# %s (%s)\n" % (get_name(thread_id), thread_id)
        for filename, lineno, name, line in traceback.extract_stack(stack):
            ret += 'File: "%s", line %d, in %s\n' % (filename, lineno, name)
            if line:
                ret += "  %s\n" % (line.strip())
    return ret

def try_get_lock_or_break_open():
    """this is an ugly hack to workaround possible deadlock problems.
    It is used during shutdown to make sure we can properly exit even when
    some slot is stuck (due to a programming error) and won't release the lock.
    If we can't acquire it within 2 seconds we just break it open forcefully."""
    #pylint: disable=W0212
    time_end = time.time() + 2
    while time.time() < time_end:
        if goxapi.Signal._lock.acquire(False):
            return
        time.sleep(0.001)

    # something keeps holding the lock, apparently some slot is stuck
    # in an infinite loop. In order to be able to shut down anyways
    # we just throw away that lock and replace it with a new one
    lock = threading.RLock()
    lock.acquire()
    goxapi.Signal._lock = lock
    print "### could not acquire signal lock, frozen slot somewhere?"
    print "### please see the stacktrace log to determine the cause."


#
#
# logging, printing, etc...
#

class LogWriter():
    """connects to gox.signal_debug and logs it all to the logfile"""
    def __init__(self, gox):
        self.gox = gox
        if self.gox.config.get_bool("goxtool", "dont_truncate_logfile"):
            logfilemode = 'a'
        else:
            logfilemode = 'w'

        logging.basicConfig(filename='goxtool.log'
                           ,filemode=logfilemode
                           ,format='%(asctime)s:%(levelname)s:%(message)s'
                           ,level=logging.DEBUG
                           )
        console = logging.StreamHandler()
        logging.getLogger('').addHandler(console)

        self.gox.signal_debug.connect(self.slot_debug)

    def close(self):
        """stop logging"""
        #not needed
        pass

    # pylint: disable=R0201
    def slot_debug(self, sender, (msg)):
        """handler for signal_debug signals"""
        name = "%s.%s" % (sender.__class__.__module__, sender.__class__.__name__)
        logging.debug("%s:%s", name, msg)


class PrintHook():
    """intercept stdout/stderr and send it all to gox.signal_debug instead"""
    def __init__(self, gox):
        self.gox = gox
        self.stdout = sys.stdout
        self.stderr = sys.stderr
        sys.stdout = self
        sys.stderr = self

    def close(self):
        """restore normal stdio"""
        sys.stdout = self.stdout
        sys.stderr = self.stderr

    def write(self, string):
        """called when someone uses print(), send it to gox"""
        string = string.strip()
        if string != "":
            self.gox.signal_debug(self, string)
            
#
#
# dynamically (re)loadable strategy module
#

class StrategyManager():
    """load the strategy module"""

    def __init__(self, gox, strategy_name_list):
        self.strategy_object_list = []
        self.strategy_name_list = strategy_name_list
        self.gox = gox
        self.reload()

    def unload(self):
        """unload the strategy, will trigger its the __del__ method"""
        self.gox.signal_strategy_unload(self, None)
        self.strategy_object_list = []

    def reload(self):
        """reload and re-initialize the strategy module"""
        self.unload()
        for name in self.strategy_name_list:
            name = name.replace(".py", "").strip()

            try:
                strategy_module = __import__(name)
                try:
                    reload(strategy_module)
                    strategy_object = strategy_module.Strategy(self.gox)
                    self.strategy_object_list.append(strategy_object)
                    if hasattr(strategy_object, "name"):
                        self.gox.strategies[strategy_object.name] = strategy_object

                except Exception:
                    self.gox.debug("### error while loading strategy %s.py, traceback follows:" % name)
                    self.gox.debug(traceback.format_exc())

            except ImportError:
                self.gox.debug("### could not import %s.py, traceback follows:" % name)
                self.gox.debug(traceback.format_exc())


def toggle_setting(gox, alternatives, option_name, direction):
    """toggle a setting in the ini file"""
    # pylint: disable=W0212
    with goxapi.Signal._lock:
        setting = gox.config.get_string("goxtool", option_name)
        try:
            newindex = (alternatives.index(setting) + direction) % len(alternatives)
        except ValueError:
            newindex = 0
        gox.config.set("goxtool", option_name, alternatives[newindex])
        gox.config.save()

def toggle_depth_group(gox, direction):
    """toggle the step width of the depth chart"""
    if gox.curr_quote in "JPY SEK":
        alt = ["5", "10", "25", "50", "100", "200", "500", "1000", "2000", "5000", "10000"]
    else:
        alt = ["0.05", "0.1", "0.25", "0.5", "1", "2", "5", "10", "20", "50", "100"]
    toggle_setting(gox, alt, "depth_chart_group", direction)
    gox.orderbook.signal_changed(gox.orderbook, None)

def toggle_orderbook_group(gox, direction):
    """toggle the group width of the orderbook"""
    if gox.curr_quote in "JPY SEK":
        alt = ["0", "5", "10", "25", "50", "100", "200", "500", "1000", "2000", "5000", "10000"]
    else:
        alt = ["0", "0.05", "0.1", "0.25", "0.5", "1", "2", "5", "10", "20", "50", "100"]
    toggle_setting(gox, alt, "orderbook_group", direction)
    gox.orderbook.signal_changed(gox.orderbook, None)

def toggle_orderbook_sum(gox):
    """toggle the summing in the orderbook on and off"""
    alt = ["False", "True"]
    toggle_setting(gox, alt, "orderbook_sum_total", 1)
    gox.orderbook.signal_changed(gox.orderbook, None)

def toggle_depth_sum(gox):
    """toggle the summing in the depth chart on and off"""
    alt = ["False", "True"]
    toggle_setting(gox, alt, "depth_chart_sum_total", 1)
    gox.orderbook.signal_changed(gox.orderbook, None)

def set_ini(gox, setting, value, signal, signal_sender, signal_params):
    """set the ini value and then send a signal"""
    # pylint: disable=W0212
    with goxapi.Signal._lock:
        gox.config.set("goxtool", setting, value)
        gox.config.save()
    signal(signal_sender, signal_params)



#
#
# main program
#

def main():
    """main funtion, called at the start of the program"""

    debug_tb = []
    def mainLoop():
        gox = goxapi.Gox(None, config, dbcon)

        logwriter = LogWriter(gox)
        printhook = PrintHook(gox)
        strategy_manager = StrategyManager(gox, strat_mod_list)

        gox.start()
        try:
            application.gox = gox
            application.listen(8888)
            tornado.ioloop.IOLoop.instance().start()
        except KeyboardInterrupt:
            # Ctrl+C has been pressed
            pass

        except Exception:
            debug_tb.append(traceback.format_exc())

        # we are here because shutdown was requested.
        #
        # Before we do anything we dump stacktraces of all currently running
        # threads to a separate logfile because this helps debugging freezes
        # and deadlocks that might occur if things went totally wrong.
        with open("goxtool.stacktrace.log", "w") as stacklog:
            stacklog.write(dump_all_stacks())

        # we need the signal lock to be able to shut down. And we cannot
        # wait for any frozen slot to return, so try really hard to get
        # the lock and if that fails then unlock it forcefully.
        try_get_lock_or_break_open()

        # Now trying to shutdown everything in an orderly manner.it in the
        # Since we are still inside curses but we don't know whether
        # the printhook or the logwriter was initialized properly already
        # or whether it crashed earlier we cannot print here and we also
        # cannot log, so we put all tracebacks into the debug_tb list to
        # print them later once the terminal is properly restored again.
        try:
            strategy_manager.unload()
        except Exception:
            debug_tb.append(traceback.format_exc())

        try:
            gox.stop()
        except Exception:
            debug_tb.append(traceback.format_exc())

        try:
            printhook.close()
        except Exception:
            debug_tb.append(traceback.format_exc())

        try:
            logwriter.close()
        except Exception:
            debug_tb.append(traceback.format_exc())

        # curses_loop() ends here, we must reach this point under all circumstances.
        # Now curses will restore the terminal back to cooked (normal) mode.


    # Here it begins. The very first thing is to always set US or GB locale
    # to have always the same well defined behavior for number formatting.
    for loc in ["en_US.UTF8", "en_GB.UTF8", "en_EN", "en_GB", "C"]:
        try:
            locale.setlocale(locale.LC_NUMERIC, loc)
            break
        except locale.Error:
            continue

    # before we can finally start the curses UI we might need to do some user
    # interaction on the command line, regarding the encrypted secret
    argp = argparse.ArgumentParser(description='MtGox live market data monitor'
        + ' and trading bot experimentation framework')
    argp.add_argument('--add-secret', action="store_true",
        help="prompt for API secret, encrypt it and then exit")
    argp.add_argument('--strategy', action="store", default="strategy.py",
        help="name of strategy module files, comma separated list, default=strategy.py")
    argp.add_argument('--protocol', action="store", default="",
        help="force protocol (socketio or websocket), ignore setting in .ini")
    argp.add_argument('--no-fulldepth', action="store_true", default=False,
        help="do not download full depth (useful for debugging)")
    argp.add_argument('--no-depth', action="store_true", default=False,
        help="do not request depth messages (implies no-fulldeph), useful for low traffic")
    argp.add_argument('--no-lag', action="store_true", default=False,
        help="do not request order-lag updates, useful for low traffic")
    argp.add_argument('--no-history', action="store_true", default=False,
        help="do not download full history (useful for debugging)")
    argp.add_argument('--use-http', action="store_true", default=False,
        help="use http api for trading (more reliable, recommended")
    argp.add_argument('--no-http', action="store_true", default=False,
        help="use streaming api for trading (problematic when streaming api disconnects often)")
    argp.add_argument('--password', action="store", default=None,
        help="password for decryption of stored key. This is a dangerous option "
            +"because the password might end up being stored in the history file "
            +"of your shell, for example in ~/.bash_history. Use this only when "
            +"starting it from within a script and then of course you need to "
            +"keep this start script in a secure place!")
    args = argp.parse_args()

    config = goxapi.GoxConfig("goxtool.ini")
    config.init_defaults(INI_DEFAULTS)
    secret = goxapi.Secret(config)
    secret.password_from_commandline_option = args.password

    if ("pymysql" in sys.modules):
        dbcon = pymysql.connect(config.get("db", "hostname", "localhost"), 
                         config.get("db", "username", ""), 
                         config.get("db", "password", ""), 
                         config.get("db", "database", ""))
    elif ("MySQLdb" in sys.modules):
        dbcon = MySQLdb.connect(config.get("db", "hostname", "localhost"), 
                        config.get("db", "username", ""), 
                        config.get("db", "password", ""), 
                        config.get("db", "database", ""))
    else:
        dbcon = None
    #dbcon = None
    
    if args.add_secret:
        # prompt for secret, encrypt, write to .ini and then exit the program
        secret.prompt_encrypt()
    else:
        strat_mod_list = args.strategy.split(",")
        goxapi.FORCE_PROTOCOL = args.protocol
        goxapi.FORCE_NO_FULLDEPTH = args.no_fulldepth
        goxapi.FORCE_NO_DEPTH = args.no_depth
        goxapi.FORCE_NO_LAG = args.no_lag
        goxapi.FORCE_NO_HISTORY = args.no_history
        goxapi.FORCE_HTTP_API = args.use_http
        goxapi.FORCE_NO_HTTP_API = args.no_http
        if goxapi.FORCE_NO_DEPTH:
            goxapi.FORCE_NO_FULLDEPTH = True

        # if its ok then we can finally enter the curses main loop
        if secret.prompt_decrypt() != secret.S_FAIL_FATAL:
            mainLoop()
            if len(debug_tb):
                print "\n\n*** error(s) in curses_loop() that caused unclean shutdown:\n"
                for trb in debug_tb:
                    print trb + "\n"
            if dbcon:
                try:
                    print "Closing database connection"
                    dbcon.close()
                except:
                    pass

if __name__ == "__main__":
    main()

