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

# class Win:
    # """represents a curses window"""
    # # pylint: disable=R0902

    # def __init__(self, stdscr):
        # """create and initialize the window. This will also subsequently
        # call the paint() method."""
        # self.stdscr = stdscr
        # self.posx = 0
        # self.posy = 0
        # self.width = 10
        # self.height = 10
        # self.termwidth = 10
        # self.termheight = 10
        # self.win = None
        # self.panel = None
        # self.__create_win()

    # def __del__(self):
        # del self.panel
        # del self.win
        # curses.panel.update_panels()
        # curses.doupdate()

    # def calc_size(self):
        # """override this method to change posx, posy, width, height.
        # It will be called before window creation and on resize."""
        # pass

    # def do_paint(self):
        # """call this if you want the window to repaint itself"""
        # self.paint()
        # self.done_paint()

    # def done_paint(self):
        # """update the sreen after paint operations, this will invoke all
        # necessary stuff to refresh all (possibly overlapping) windows in
        # the right order and then push it to the screen"""
        # self.win.touchwin()
        # curses.panel.update_panels()
        # curses.doupdate()

    # def paint(self):
        # """paint the window. Override this with your own implementation.
        # This method must paint the entire window contents from scratch.
        # It is automatically called after the window has been initially
        # created and also after every resize. Call it explicitly when
        # your data has changed and must be displayed"""
        # pass

    # def resize(self):
        # """You must call this method from your main loop when the
        # terminal has been resized. It will subsequently make it
        # recalculate its own new size and then call its paint() method"""
        # del self.win
        # self.__create_win()

    # def addstr(self, *args):
        # """drop-in replacement for addstr that will never raie exceptions
        # and that will cut off at end of line instead of wrapping"""
        # if len(args) > 0:
            # line, col = self.win.getyx()
            # string = args[0]
            # attr = 0
        # if len(args) > 1:
            # attr = args[1]
        # if len(args) > 2:
            # line, col, string = args[:3]
            # attr = 0
        # if len(args) > 3:
            # attr = args[3]
        # if line >= self.height:
            # return
        # space_left = self.width - col - 1 #always omit last column, avoids problems.
        # if space_left <= 0:
            # return
        # self.win.addstr(line, col, string[:space_left], attr)

    # def addch(self, posy, posx, character, color_pair):
        # """place a character but don't throw error in lower right corner"""
        # if posy < 0 or posy > self.height - 1:
            # return
        # if posx < 0 or posx > self.width - 1:
            # return
        # if posx == self.width - 1 and posy == self.height - 1:
            # return
        # self.win.addch(posy, posx, character, color_pair)

    # def __create_win(self):
        # """create the window. This will also be called on every resize,
        # windows won't be moved, they will be deleted and recreated."""
        # self.__calc_size()
        # self.win = curses.newwin(self.height, self.width, self.posy, self.posx)
        # self.panel = curses.panel.new_panel(self.win)
        # self.win.scrollok(True)
        # self.win.keypad(1)
        # self.do_paint()

    # def __calc_size(self):
        # """calculate the default values for positionand size. By default
        # this will result in a window covering the entire terminal.
        # Implement the calc_size() method (which will be called afterwards)
        # to change (some of) these values according to your needs."""
        # maxyx = self.stdscr.getmaxyx()
        # self.termwidth = maxyx[1]
        # self.termheight = maxyx[0]
        # self.posx = 0
        # self.posy = 0
        # self.width = self.termwidth
        # self.height = self.termheight
        # self.calc_size()


# class WinConsole(Win):
    # """The console window at the bottom"""
    # def __init__(self, stdscr, gox):
        # """create the console window and connect it to the Gox debug
        # callback function"""
        # self.gox = gox
        # gox.signal_debug.connect(self.slot_debug)
        # Win.__init__(self, stdscr)

    # def paint(self):
        # """just empty the window after resize (I am lazy)"""
        # self.win.bkgd(" ", COLOR_PAIR["con_text"])

    # def resize(self):
        # """resize and print a log message. Old messages will have been
        # lost after resize because of my dumb paint() implementation, so
        # at least print a message indicating that fact into the
        # otherwise now empty console window"""
        # Win.resize(self)
        # self.write("### console has been resized")

    # def calc_size(self):
        # """put it at the bottom of the screen"""
        # self.height = HEIGHT_CON
        # self.posy = self.termheight - self.height

    # def slot_debug(self, dummy_gox, (txt)):
        # """this slot will be connected to all debug signals."""
        # self.write(txt)

    # def write(self, txt):
        # """write a line of text, scroll if needed"""
        # self.win.addstr("\n" + txt,  COLOR_PAIR["con_text"])
        # self.done_paint()


# class WinOrderBook(Win):
    # """the orderbook window"""

    # def __init__(self, stdscr, gox):
        # """create the orderbook window and connect it to the
        # onChanged callback of the gox.orderbook instance"""
        # self.gox = gox
        # gox.orderbook.signal_changed.connect(self.slot_changed)
        # Win.__init__(self, stdscr)

    # def calc_size(self):
        # """put it into the middle left side"""
        # self.height = self.termheight - HEIGHT_CON - HEIGHT_STATUS
        # self.posy = HEIGHT_STATUS
        # self.width = WIDTH_ORDERBOOK

    # def paint(self):
        # """paint the visible portion of the orderbook"""

        # def paint_row(xpos, ypos, price, vol, ownvol, color):
            # """paint a row in the orderbook (bid or ask)"""
            # self.addstr(ypos, xpos,  goxapi.int2str(price, book.gox.currency), color)
            # self.addstr(ypos, xpos+12, goxapi.int2str(vol, "BTC"), col_vol)
            # if ownvol:
                # self.addstr(ypos, xpos+28, goxapi.int2str(ownvol, "BTC"), col_own)

        # self.win.bkgd(" ",  COLOR_PAIR["book_text"])
        # self.win.erase()
        # mid = self.height / 2
        # col_bid = COLOR_PAIR["book_bid"]
        # col_ask = COLOR_PAIR["book_ask"]
        # col_vol = COLOR_PAIR["book_vol"]
        # col_own = COLOR_PAIR["book_own"]

        # sum_total = self.gox.config.get_bool("goxtool", "orderbook_sum_total")
        # group = self.gox.config.get_float("goxtool", "orderbook_group")
        # group = goxapi.float2int(group, self.gox.currency)
        # if group == 0:
            # group = 1

        # # print the asks
        # book = self.gox.orderbook
        # cnt = len(book.asks)

        # ypos = self.height
        # i = 0
        # vol = 0
        # ownvol = 0
        # while ypos >= 0 and  i < cnt:
            # price = book.asks[i].price
            # if i == 0:
                # this_bin = price
                # vol = book.asks[i].volume
                # ownvol = book.get_own_volume_at(price, "ask")
            # else:
                # if price <= this_bin:
                    # # still the same bin, add volumes
                    # vol += book.asks[i].volume
                    # ownvol += book.get_own_volume_at(price, "ask")
                # else:
                    # # paint the existing bin and...
                    # paint_row(40, ypos, this_bin, vol, ownvol, col_ask)
                    # ypos -= 1
                    # # ...begin a new bin
                    # this_bin = int(math.ceil(float(price) / group) * group)
                    # if sum_total:
                        # vol += book.asks[i].volume
                    # else:
                        # vol = book.asks[i].volume
                    # ownvol = book.get_own_volume_at(price, "ask")
            # i += 1
        # if cnt and ypos >= 0:
            # paint_row(35, ypos, this_bin, vol, ownvol, col_ask)

        # # print the bids
        # cnt = len(book.bids)
        # ypos = self.height
        # i = 0
        # vol = 0
        # ownvol = 0
        # while ypos >= 0 and  i < cnt:
            # price = book.bids[i].price
            # if i == 0:
                # this_bin = price
                # vol = book.bids[i].volume
                # ownvol = book.get_own_volume_at(price, "bid")
            # else:
                # if price >= this_bin:
                    # # still the same bin, add volumes
                    # vol += book.bids[i].volume
                    # ownvol += book.get_own_volume_at(price, "bid")
                # else:
                    # # paint the current bin and...
                    # paint_row(0, ypos, this_bin, vol, ownvol, col_bid)
                    # ypos -= 1
                    # # ...begin a new bin
                    # this_bin = int(math.floor(float(price) / group) * group)
                    # if sum_total:
                        # vol += book.bids[i].volume
                    # else:
                        # vol = book.bids[i].volume
                    # ownvol = book.get_own_volume_at(price, "bid")
            # i += 1
        # if cnt and ypos >= 0:
            # paint_row(0, ypos, this_bin, vol, ownvol, col_bid)


    # def slot_changed(self, book, dummy_data):
        # """Slot for orderbook.signal_changed"""
        # self.do_paint()

        # # update the xterm title (this is not handled by curses)
        # if self.gox.config.get_bool("goxtool", "set_xterm_title"):
            # last_candle = self.gox.history.last_candle()
            # if last_candle:
                # title = goxapi.int2str(last_candle.cls, self.gox.currency).strip()
                # title += " - goxtool -"
                # title += " bid:" + goxapi.int2str(book.bid, self.gox.currency).strip()
                # title += " ask:" + goxapi.int2str(book.ask, self.gox.currency).strip()
                # curses.putp("\033]0;%s\007" % title)


# class WinChart(Win):
    # """the chart window"""

    # def __init__(self, stdscr, gox):
        # self.gox = gox
        # self.pmin = 0
        # self.pmax = 0
        # gox.history.signal_changed.connect(self.slot_hist_changed)
        # gox.orderbook.signal_changed.connect(self.slot_book_changed)
        # Win.__init__(self, stdscr)

    # def calc_size(self):
        # """position in the middle, right to the orderbook"""
        # self.posx = WIDTH_ORDERBOOK
        # self.posy = HEIGHT_STATUS
        # self.width = self.termwidth - WIDTH_ORDERBOOK
        # self.height = self.termheight - HEIGHT_CON - HEIGHT_STATUS

    # def is_in_range(self, price):
        # """is this price in the currently viible range?"""
        # return price <= self.pmax and price >= self.pmin

    # def get_optimal_step(self, num_min):
        # """return optimal step size for painting y-axis labels so that the
        # range will be divided into at least num_min steps"""
        # if self.pmax <= self.pmin:
            # return None
        # stepex = float(self.pmax - self.pmin) / num_min
        # step1 = math.pow(10, math.floor(math.log(stepex, 10)))
        # step2 = step1 * 2
        # step5 = step1 * 5
        # if step5 <= stepex:
            # return step5
        # if step2 <= stepex:
            # return step2
        # return step1

    # def price_to_screen(self, price):
        # """convert price into screen coordinates (y=0 is at the top!)"""
        # relative_from_bottom = \
            # float(price - self.pmin) / float(self.pmax - self.pmin)
        # screen_from_bottom = relative_from_bottom * self.height
        # return int(self.height - screen_from_bottom)

    # def paint_candle(self, posx, candle):
        # """paint a single candle"""

        # sopen  = self.price_to_screen(candle.opn)
        # shigh  = self.price_to_screen(candle.hig)
        # slow   = self.price_to_screen(candle.low)
        # sclose = self.price_to_screen(candle.cls)

        # for posy in range(self.height):
            # if posy >= shigh and posy < sopen and posy < sclose:
                # # upper wick
                # # pylint: disable=E1101
                # self.addch(posy, posx,
                    # curses.ACS_VLINE, COLOR_PAIR["chart_text"])
            # if posy >= sopen and posy < sclose:
                # # red body
                # self.addch(posy, posx,
                    # ord(" "), curses.A_REVERSE + COLOR_PAIR["chart_down"])
            # if posy >= sclose and posy < sopen:
                # # green body
                # self.addch(posy, posx,
                    # ord(" "), curses.A_REVERSE + COLOR_PAIR["chart_up"])
            # if posy >= sopen and posy >= sclose and posy < slow:
                # # lower wick
                # # pylint: disable=E1101
                # self.addch(posy, posx,
                    # curses.ACS_VLINE, COLOR_PAIR["chart_text"])

    # def paint(self):
        # """paint the visible portion of the chart"""


        # self.win.bkgd(" ",  COLOR_PAIR["chart_text"])
        # self.win.erase()

        # hist = self.gox.history
        # book = self.gox.orderbook

        # self.pmax = 0
        # self.pmin = 9999999999

        # # determine y range
        # posx = self.width - 2
        # index = 0
        # while index < hist.length() and posx >= 0:
            # candle = hist.candles[index]
            # if self.pmax < candle.hig:
                # self.pmax = candle.hig
            # if self.pmin > candle.low:
                # self.pmin = candle.low
            # index += 1
            # posx -= 1

        # if self.pmax == self.pmin:
            # return

        # # paint the candles
        # posx = self.width - 2
        # index = 0
        # while index < hist.length() and posx >= 0:
            # candle = hist.candles[index]
            # self.paint_candle(posx, candle)
            # index += 1
            # posx -= 1

        # # paint bid, ask, own orders
        # posx = self.width - 1
        # for order in book.owns:
            # if self.is_in_range(order.price):
                # posy = self.price_to_screen(order.price)
                # if order.status == "pending":
                    # self.addch(posy, posx,
                        # ord("o"), COLOR_PAIR["order_pending"])
                # else:
                    # self.addch(posy, posx,
                        # ord("O"), COLOR_PAIR["chart_text"])

        # if self.is_in_range(book.bid):
            # posy = self.price_to_screen(book.bid)
            # # pylint: disable=E1101
            # self.addch(posy, posx,
                # curses.ACS_HLINE, COLOR_PAIR["chart_up"])

        # if self.is_in_range(book.ask):
            # posy = self.price_to_screen(book.ask)
            # # pylint: disable=E1101
            # self.addch(posy, posx,
                # curses.ACS_HLINE, COLOR_PAIR["chart_down"])

        # # paint the y-axis labels
        # posx = 0
        # step = self.get_optimal_step(4)
        # if step:
            # labelprice = int(self.pmin / step) * step
            # while not labelprice > self.pmax:
                # posy = self.price_to_screen(labelprice)
                # if posy < self.height - 1:
                    # self.addstr(
                        # posy, posx,
                        # goxapi.int2str(labelprice, self.gox.currency),
                        # COLOR_PAIR["chart_text"]
                    # )
                # labelprice += step

    # def slot_hist_changed(self, dummy_history, (dummy_cnt)):
        # """Slot for history.signal_changed"""
        # self.do_paint()

    # def slot_book_changed(self, dummy_book, dummy_data):
        # """Slot for orderbook.signal_changed"""
        # self.do_paint()


# class WinStatus(Win):
    # """the status window at the top"""

    # def __init__(self, stdscr, gox):
        # """create the status window and connect the needed callbacks"""
        # self.gox = gox
        # self.order_lag = 0
        # self.order_lag_txt = ""
        # self.sorted_currency_list = []
        # gox.signal_orderlag.connect(self.slot_orderlag)
        # gox.signal_wallet.connect(self.slot_changed)
        # gox.orderbook.signal_changed.connect(self.slot_changed)
        # Win.__init__(self, stdscr)

    # def calc_size(self):
        # """place it at the top of the terminal"""
        # self.height = HEIGHT_STATUS

    # def sort_currency_list_if_changed(self):
        # """sort the currency list in the wallet for better display,
        # sort it only if it has changed, otherwise leave it as it is"""
        # currency_list = self.gox.wallet.keys()
        # if len(currency_list) == len(self.sorted_currency_list):
            # return

        # # now we will bring BTC and gox.currency to the front and sort the
        # # the rest of the list of names by acount balance in descending order
        # currency_list.remove("BTC")
        # currency_list.remove(self.gox.currency)
        # currency_list.sort(key=lambda name: -self.gox.wallet[name])
        # currency_list.insert(0, self.gox.currency)
        # currency_list.insert(0, "BTC")
        # self.sorted_currency_list = currency_list

    # def paint(self):
        # """paint the complete status"""
        # self.sort_currency_list_if_changed()
        # self.win.bkgd(" ", COLOR_PAIR["status_text"])
        # self.win.erase()
        # line1 = "Currency: " + self.gox.currency + " | "
        # line1 += "Account: "
        # if len(self.sorted_currency_list):
            # for currency in self.sorted_currency_list:
                # line1 += currency + " " \
                # + goxapi.int2str(self.gox.wallet[currency], currency).strip() \
                # + " + "
            # line1 = line1.strip(" +")
        # else:
            # line1 += "No info (yet)"

        # str_btc = locale.format('%d', self.gox.orderbook.total_ask, 1)
        # str_fiat = locale.format('%d', self.gox.orderbook.total_bid, 1)
        # if self.gox.orderbook.total_ask:
            # str_ratio = locale.format('%1.2f',
                # self.gox.orderbook.total_bid / self.gox.orderbook.total_ask, 1)
        # else:
            # str_ratio = "-"

        # line2 = "total bid: " + str_fiat + " " + self.gox.currency + " | "
        # line2 += "total ask: " +str_btc + " BTC | "
        # line2 += "ratio: " + str_ratio + " " + self.gox.currency + "/BTC | "
        # line2 += "lag: " + self.order_lag_txt
        # self.addstr(0, 0, line1, COLOR_PAIR["status_text"])
        # self.addstr(1, 0, line2, COLOR_PAIR["status_text"])


    # def slot_changed(self, dummy_sender, dummy_data):
        # """the callback funtion called by the Gox() instance"""
        # self.do_paint()

    # def slot_orderlag(self, dummy_sender, (usec, text)):
        # """slot for order_lag mesages"""
        # self.order_lag = usec
        # self.order_lag_txt = text
        # self.do_paint()


# class DlgListItems(Win):
    # """dialog with a scrollable list of items"""
    # def __init__(self, stdscr, width, title, hlp, keys):
        # self.items = []
        # self.selected = []
        # self.item_top = 0
        # self.item_sel = 0
        # self.dlg_width = width
        # self.dlg_title = title
        # self.dlg_hlp = hlp
        # self.dlg_keys = keys
        # self.reserved_lines = 5  # how many lines NOT used for order list
        # self.init_items()
        # Win.__init__(self, stdscr)

    # def init_items(self):
        # """initialize the items list, must override and implement this"""
        # raise NotImplementedError()

    # def calc_size(self):
        # maxh = self.termheight - 4
        # self.height = len(self.items) + self.reserved_lines
        # if self.height > maxh:
            # self.height = maxh
        # self.posy = (self.termheight - self.height) / 2

        # self.width = self.dlg_width
        # self.posx = (self.termwidth - self.width) / 2

    # def paint_item(self, posx, index):
        # """paint the item. Must override and implement this"""
        # raise NotImplementedError()

    # def paint(self):
        # self.win.bkgd(" ", COLOR_PAIR["dialog_text"])
        # self.win.erase()
        # self.win.border()
        # self.addstr(0, 1, " %s " % self.dlg_title, COLOR_PAIR["dialog_text"])
        # index = self.item_top
        # posy = 2
        # while posy < self.height - 3 and index < len(self.items):
            # self.paint_item(posy, index)
            # index += 1
            # posy += 1

        # self.win.move(self.height - 2, 2)
        # for key, desc in self.dlg_hlp:
            # self.addstr(key + " ",  COLOR_PAIR["dialog_sel"])
            # self.addstr(desc + " ", COLOR_PAIR["dialog_text"])

    # def down(self, num):
        # """move the cursor down (or up)"""
        # if not len(self.items):
            # return
        # self.item_sel += num
        # if self.item_sel < 0:
            # self.item_sel = 0
        # if self.item_sel > len(self.items) - 1:
            # self.item_sel = len(self.items) - 1

        # last_line = self.height - 1 - self.reserved_lines
        # if self.item_sel < self.item_top:
            # self.item_top = self.item_sel
        # if self.item_sel - self.item_top > last_line:
            # self.item_top = self.item_sel - last_line

        # self.do_paint()

    # def toggle_select(self):
        # """toggle selection under cursor"""
        # if not len(self.items):
            # return
        # item = self.items[self.item_sel]
        # if item in self.selected:
            # self.selected.remove(item)
        # else:
            # self.selected.append(item)
        # self.do_paint()

    # def modal(self):
        # """run the modal getch-loop for this dialog"""
        # done = False
        # while not done:
            # key_pressed = self.win.getch()
            # if key_pressed in [27, ord("q"), curses.KEY_F10]:
                # done = True
            # if key_pressed == curses.KEY_DOWN:
                # self.down(1)
            # if key_pressed == curses.KEY_UP:
                # self.down(-1)
            # if key_pressed == curses.KEY_IC:
                # self.toggle_select()
                # self.down(1)

            # for key, func in self.dlg_keys:
                # if key == key_pressed:
                    # func()
                    # done = True

        # # help the garbage collector clean up circular references
        # # to make sure __del__() will be called to close the dialog
        # del self.dlg_keys


# class DlgCancelOrders(DlgListItems):
    # """modal dialog to cancel orders"""
    # def __init__(self, stdscr, gox):
        # self.gox = gox
        # hlp = [("INS", "select"), ("Del", "cancel selected"), ("F10", "exit")]
        # keys = [(curses.KEY_DC, self._do_cancel)]
        # DlgListItems.__init__(self, stdscr, 45, "Cancel order(s)", hlp, keys)

    # def init_items(self):
        # for order in self.gox.orderbook.owns:
            # self.items.append(order)
        # self.items.sort(key = lambda o: -o.price)

    # def paint_item(self, posy, index):
        # """paint one single order"""
        # order = self.items[index]
        # if order in self.selected:
            # marker = "*"
            # if index == self.item_sel:
                # attr = COLOR_PAIR["dialog_sel_sel"]
            # else:
                # attr = COLOR_PAIR["dialog_sel_text"] + curses.A_BOLD
        # else:
            # marker = ""
            # if index == self.item_sel:
                # attr = COLOR_PAIR["dialog_sel"]
            # else:
                # attr = COLOR_PAIR["dialog_text"]

        # self.addstr(posy, 2, marker, attr)
        # self.addstr(posy, 5, order.typ, attr)
        # self.addstr(posy, 9, goxapi.int2str(order.price, self.gox.currency), attr)
        # self.addstr(posy, 22, goxapi.int2str(order.volume, "BTC"), attr)

    # def _do_cancel(self):
        # """cancel all selected orders (or the order under cursor if empty)"""

        # def do_cancel(order):
            # """cancel a single order"""
            # self.gox.cancel(order.oid)

        # if not len(self.items):
            # return
        # if not len(self.selected):
            # order = self.items[self.item_sel]
            # do_cancel(order)
        # else:
            # for order in self.selected:
                # do_cancel(order)


# class TextBox():
    # """wrapper for curses.textpad.Textbox"""

    # def __init__(self, dlg, posy, posx, length):
        # self.dlg = dlg
        # self.win = dlg.win.derwin(1, length, posy, posx)
        # self.win.keypad(1)
        # self.box = curses.textpad.Textbox(self.win, insert_mode=True)
        # self.value = ""
        # self.result = None
        # self.editing = False

    # def __del__(self):
        # self.box = None
        # self.win = None

    # def modal(self):
        # """enter te edit box modal loop"""
        # self.win.move(0, 0)
        # self.editing = True
        # threading.Thread(None, self.cursor_placement_thread).start()
        # self.value = self.box.edit(self.validator)
        # self.editing = False
        # return self.result

    # def validator(self, char):
        # """here we tweak the behavior slightly, especially we want to
        # end modal editing mode immediately on arrow up/down and on enter
        # and we also want to catch ESC and F10, to abort the entire dialog"""
        # if curses.ascii.isprint(char):
            # return char
        # if char == curses.ascii.TAB:
            # char = curses.KEY_DOWN
        # if char in [curses.KEY_DOWN, curses.KEY_UP]:
            # self.result = char
            # return curses.ascii.BEL
        # if char in [10, 13, curses.KEY_ENTER, curses.ascii.BEL]:
            # self.result = 10
            # return curses.ascii.BEL
        # if char in [27, curses.KEY_F10]:
            # self.result = -1
            # return curses.ascii.BEL
        # return char

    # def cursor_placement_thread(self):
        # """this is the most ugly hack of the entire program. During the
        # signals hat are fired while we are editing there will be many repaints
        # of other other panels below this dialog and when curses is done
        # repainting everything the blinking cursor is not in the correct
        # position. This is only a cosmetic problem but very annnoying. Try to
        # force it into the edit field by repainting it very often."""
        # while self.editing:
            # # pylint: disable=W0212
            # with goxapi.Signal._lock:
                # self.win.touchwin()
                # self.win.refresh()
            # time.sleep(0.1)


# class NumberBox(TextBox):
    # """TextBox that only accepts numbers"""
    # def __init__(self, dlg, posy, posx, length):
        # TextBox.__init__(self, dlg, posy, posx, length)

    # def validator(self, char):
        # """allow only numbers to be entered"""
        # if char == ord("q"):
            # char = curses.KEY_F10
        # if curses.ascii.isprint(char):
            # if chr(char) not in "0123456789.":
                # char = 0
        # return TextBox.validator(self, char)


# class DlgNewOrder(Win):
    # """abtract base class for entering new orders"""
    # def __init__(self, stdscr, gox, color, title):
        # self.gox = gox
        # self.color = color
        # self.title = title
        # self.edit_price = None
        # self.edit_volume = None
        # Win.__init__(self, stdscr)

    # def calc_size(self):
        # Win.calc_size(self)
        # self.width = 35
        # self.height = 8
        # self.posx = (self.termwidth - self.width) / 2
        # self.posy = (self.termheight - self.height) / 2

    # def paint(self):
        # self.win.bkgd(" ", self.color)
        # self.win.border()
        # self.addstr(0, 1, " %s " % self.title, self.color)
        # self.addstr(2, 2, " price", self.color)
        # self.addstr(4, 2, "volume", self.color)
        # self.addstr(6, 2, "F10 ", self.color + curses.A_REVERSE)
        # self.addstr("cancel ", self.color)
        # self.addstr("Enter ", self.color + curses.A_REVERSE)
        # self.addstr("submit ", self.color)
        # self.edit_price = NumberBox(self, 2, 10, 20)
        # self.edit_volume = NumberBox(self, 4, 10, 20)

    # def do_submit(self, price_float, volume_float):
        # """sumit the order. implementating class will do eiter buy or sell"""
        # raise NotImplementedError()

    # def modal(self):
        # """enter the modal getch() loop of this dialog"""
        # focus = 1
        # # next time I am going to use some higher level
        # # wrapper on top of curses, i promise...
        # while True:
            # if focus == 1:
                # res = self.edit_price.modal()
                # if res == -1:
                    # break # cancel entire dialog
                # if res in [10, curses.KEY_DOWN, curses.KEY_UP]:
                    # try:
                        # price_float = float(self.edit_price.value)
                        # focus = 2
                    # except ValueError:
                        # pass # can't move down until this is a valid number

            # if focus == 2:
                # res = self.edit_volume.modal()
                # if res == -1:
                    # break # cancel entire dialog
                # if res in [curses.KEY_UP, curses.KEY_DOWN]:
                    # focus = 1
                # if res == 10:
                    # try:
                        # volume_float = float(self.edit_volume.value)
                        # break # have both values now, can submit order
                    # except ValueError:
                        # pass # no float number, stay in this edit field

        # if res == -1:
            # #user has hit f10. just end here, do nothing
            # pass
        # if res == 10:
            # self.do_submit(price_float, volume_float)

        # # make sure all cyclic references are garbage collected or
        # # otherwise the curses window won't disappear
        # self.edit_price = None
        # self.edit_volume = None


# class DlgNewOrderBid(DlgNewOrder):
    # """Modal dialog for new buy order"""
    # def __init__(self, stdscr, gox):
        # DlgNewOrder.__init__(self, stdscr, gox,
            # COLOR_PAIR["dialog_bid_text"],
            # "New buy order")

    # def do_submit(self, price, volume):
        # price = goxapi.float2int(price, self.gox.currency)
        # volume = goxapi.float2int(volume, "BTC")
        # self.gox.buy(price, volume)


# class DlgNewOrderAsk(DlgNewOrder):
    # """Modal dialog for new sell order"""
    # def __init__(self, stdscr, gox):
        # DlgNewOrder.__init__(self, stdscr, gox,
             # COLOR_PAIR["dialog_ask_text"],
            # "New sell order")

    # def do_submit(self, price, volume):
        # price = goxapi.float2int(price, self.gox.currency)
        # volume = goxapi.float2int(volume, "BTC")
        # self.gox.sell(price, volume)



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

