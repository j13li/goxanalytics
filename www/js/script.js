var _ws;
var _lastPriceVal;
var _lastOBVal;
var _updateChart = true;
var _lastExp = 0;
var _lastLin = 0;
var _gotPrice = false;
var _gotOB = false;
var _chartObj;
var _isAbove = true;
var _isBelow = true;
var _expQueue = [];
var _priceQueue = [];
var _checkIntervalMinutes = 10;

$(document).ready(function () {
// Create the chart
    $('#container').highcharts('StockChart', {
        chart: {
            backgroundColor: "black",
            plotBackgroundColor: "black",
            zoomType: 'x'
            //height: ($(document).height() - 60)
        },
        credits: {
            enabled: false
        },
        xAxis: {
            type: 'datetime',
            ordinal: false,
            // now that live data is no more, limit ourselves to 
            // the date range for which data is available...
            min:Date.UTC(2013,3,1),
            max:Date.UTC(2014,2,1)
        },
        yAxis: [{
            opposite: true,
            labels: {
                align: "right",
                zIndex: 100
            },
			height: ($('#container').height() - 160) / 2 - 50
            //height: (($(document).height() - 60) - 250) / 2
        }, {
			min: 0,
            opposite: true,
            labels: {
                align: "right",
                zIndex: 100
            },
			height: ($('#container').height() - 160) / 2 - 50,
			top: ($('#container').height() - 160) / 2 + 50
            //height: (($(document).height() - 60) - 250) / 2,
            //top: (($(document).height() - 60) - 250) / 2 + 100
        }],
        rangeSelector: {
            buttonTheme: {
                fill: 'none',
                style: {
                    color: 'gray'
                },
                states: {
                    hover: {
                        fill: '#039'
                    },
                    select: {
                        fill: 'none',
                        style: {
                            color: 'white'
                        }
                    }
                }
            },
            inputStyle: {
                color: '#2f7ed8'
            },
            buttons: [{
                type: 'hour',
                count: 1,
                text: '1h'
            }, {
                type: 'hour',
                count: 3,
                text: '3h'
            }, {
                type: 'hour',
                count: 12,
                text: '12h'
            }, {
                type: 'day',
                count: 1,
                text: '1d'
            }, {
                type: 'day',
                count: 3,
                text: '3d'
            }, {
                type: 'week',
                count: 1,
                text: '1w'
            }, {
                type: 'month',
                count: 1,
                text: '1m'
            }, {
                type: 'month',
                count: 6,
                text: '6m'
            }, {
                type: 'year',
                count: 1,
                text: '1y'
            }, {
                type: 'all',
                text: 'All'
            }]
			, selected: 2
        },
        tooltip: {
            valueDecimals: 3,
            backgroundColor: {
                linearGradient: {
                    x1: 0,
                    y1: 0,
                    x2: 0,
                    y2: 0
                },
                stops: [
                    [0, 'rgba(0, 0, 0, .5)']
                ]
            },
            style: {
                color: 'gray'
            },
            hideDelay: 2000
        },
        legend: {
            enabled: true,
            borderWidth: 0,
            itemHoverStyle: {
                color: 'gray'
            },
            itemStyle: {
                color: '#CCC'
            }
        },
        navigator: {
            maskFill: 'rgba(100, 100, 100, 0.5)'
        },
        navigation: {
            buttonOptions: {
                enabled: false
            }
        },
        series: [{
            name: "OB Ratio",
            data: [[0,0]],
            tooltip: {
                valueDecimals: 3
            },
            yAxis: 1
        }, {
            name: "Bandpass",
            data: [[0,0]],
            tooltip: {
                valueDecimals: 3
            },
            //visible: false,
            yAxis: 1
        }, {
            name: "Exponential",
            data: [[0,0]],
            tooltip: {
                valueDecimals: 3
            },
            yAxis: 1
        }, {
            name: "Linear",
            data: [[0,0]],
            tooltip: {
                valueDecimals: 3
            },
            yAxis: 1
        }, {
            name: "Price",
            data: [[0,0]],
            tooltip: {
                valueDecimals: 3
            },
            yAxis: 0,
            showInLegend: false,
            color: '#2f7ed8'
        }]
    });
    _chartObj = $('#container').highcharts();
    _chartObj.showLoading();
    connect();
    setInterval(function() { 
        if(_gotPrice && _lastPriceVal > 0) {
            _priceQueue.push(_lastPriceVal);
        }
        if(_gotOB && _lastExp > 0) {
            _expQueue.push(_lastExp);
        }
        while(_expQueue.length > _checkIntervalMinutes) {
            _expQueue.shift();
        }
        while(_priceQueue.length > _checkIntervalMinutes) {
            _priceQueue.shift();
        }
    }, 60 * 1000);
});
function reconnect() {
	if(_ws) {
		_ws.refresh();
	}
	else {
		connect();
	}
}

function connect() {
    _ws = new ReconnectingWebSocket("ws://hfcs.uwaterloo.ca:8888/websocket");
    _ws.onopen = function () {
        _ws.send("Price");
        _ws.send("OBVol");
    }
    _ws.onmessage = MessageHandler;
}

function MessageHandler(evt) {
    data = jQuery.parseJSON(evt.data);
    if (data.key == "Price") {
        var priceData = data.values.map(function (series) {
            series.values = series.values.map(function (d) {
                return [d[0] * 1000, d[1]];
            });
            return series;
        })[0].values;
        if (priceData.length != 1) {
            _chartObj.series[4].setData(priceData, false);
            _gotPrice = true;
            if(_gotOB) {
                _chartObj.redraw();
                _chartObj.hideLoading();
                _chartObj.rangeSelector.clickButton(2, {type: 'hour', count: 12}, true)
            }
        } else if (_chartObj && _gotPrice && _updateChart) {
            xAxis = _chartObj.xAxis[0];
            oldDataMax = xAxis.dataMax;
            for (var i in priceData) {
                _chartObj.series[4].addPoint([priceData[i][0], priceData[i][1], false, false, false]);
            }
            
            if($("#priceDownSoundCheck").is(':checked')) {
                if(_lastPriceVal > priceData[priceData.length - 1][1] && (priceData[priceData.length - 1][1] < parseFloat($("#priceDownSoundVal").val()))) {
                    $('embed').remove();
                    $('body').append('<embed src="sounds/low-arpeg.mp3" autostart="true" hidden="true" loop="false">');
                }
            }
            if($("#priceUpSoundCheck").is(':checked')) {
                if (_lastPriceVal < priceData[priceData.length - 1][1] && (priceData[priceData.length - 1][1] > parseFloat($("#priceUpSoundVal").val()))) {
                    $('embed').remove();
                    $('body').append('<embed src="sounds/low-gliss.mp3" autostart="true" hidden="true" loop="false">');
                }
            }
            if($("#priceMoveDownSoundCheck").is(':checked')) {
                if(_priceQueue.length > 0 && priceData[priceData.length - 1][1] - parseFloat($("#priceMoveDownSoundVal").val()) > Math.min.apply(null, _priceQueue)) {
                    $('embed').remove();
                    $('body').append('<embed src="sounds/sound07.mp3" autostart="true" hidden="true" loop="false">');
                }
            }
            if($("#priceMoveUpSoundCheck").is(':checked')) {
                if(_priceQueue.length > 0 && priceData[priceData.length - 1][1] + parseFloat($("#priceMoveUpSoundVal").val()) < Math.max.apply(null, _priceQueue)) {
                    $('embed').remove();
                    $('body').append('<embed src="sounds/fanfare01.mp3" autostart="true" hidden="true" loop="false">');
                }
            }
            _chartObj.redraw();
        }
        lastPrice = priceData[priceData.length - 1];
        _lastPriceVal = lastPrice[1].toFixed(5);
        if (_lastPriceVal && _lastOBVal) {
            document.title = _lastPriceVal + " / " + _lastOBVal;
        }
    }
    if (data.key == "OBVol") {
        var OBVol = data.values.map(function (d) {
            return [d[0] * 1000, d[1], d[2], d[3], d[4]];
        });

        if(!_gotPrice && OBVol.length <= 1) {
            return;
        } 
        try {
            _lastOBVal = OBVol[0][1].toFixed(5);
            if (_lastPriceVal && _lastOBVal) {
                document.title = _lastPriceVal + " / " + _lastOBVal;
            }
        } catch (e) {}
        if (OBVol.length > 1) {            
            _chartObj.series[0].setData(OBVol.map(function (d) {
                return [d[0], d[1]];
            }), false);
            _chartObj.series[1].setData(OBVol.map(function (d) {
                return [d[0], d[2]];
            }), false);
            _chartObj.series[2].setData(OBVol.map(function (d) {
                return [d[0], d[3]];
            }), false);
            _chartObj.series[3].setData(OBVol.map(function (d) {
                return [d[0], d[4]];
            }), false);
            _gotOB = true;
            if(_gotPrice) {
				if($("#maxCheck").is(':checked')) {
					yAxis = _chartObj.yAxis[1];
					yAxis.setExtremes(0, parseFloat($("#maxCheck").val()), true, false);					
				}
                _chartObj.redraw();
                _chartObj.hideLoading();
                _chartObj.rangeSelector.clickButton(2, {type: 'hour', count: 12}, true)
            }
            //$('#container').before('<div style="z-index: 1; position: fixed; right: 350px; top: 13px;">Y axis limits: <input size=5 id="yMin" onchange="yLimitHandler(event);"></input> to <input size=5 id="yMax" onchange="yLimitHandler(event);"></input></div>');
        } else if (_gotOB && _updateChart) {
            xAxis = _chartObj.xAxis[0];
            oldDataMax = xAxis.dataMax;
 
            for (var i in OBVol) {
                _chartObj.series[0].addPoint([OBVol[i][0], OBVol[i][1], false, false, false])
                _chartObj.series[1].addPoint([OBVol[i][0], OBVol[i][2], false, false, false])
                _chartObj.series[2].addPoint([OBVol[i][0], OBVol[i][3], false, false, false])
                _chartObj.series[3].addPoint([OBVol[i][0], OBVol[i][4], false, false, false])
                
                if($("#downSoundCheck").is(':checked')) {
                    if(_lastExp < OBVol[i][3] && (OBVol[i][3] > parseFloat($("#downSoundVal").val()))) { //|| OBVol[i][3] > OBVol[i][2])) {
                        $('embed').remove();
                        $('body').append('<embed src="sounds/low-arpeg.mp3" autostart="true" hidden="true" loop="false">');
                    }
                }
                if($("#upSoundCheck").is(':checked')) {
                    //if((_lastLin > OBVol[i][4] && (OBVol[i][4] <= 1 || OBVol[i][4] <= OBVol[i][1])) ||
                    //         (_lastExp > OBVol[i][3] && OBVol[i][3] < 0.65)) {
                    if (_lastExp > OBVol[i][3] && OBVol[i][3] < parseFloat($("#upSoundVal").val())) {
                        $('embed').remove();
                        $('body').append('<embed src="sounds/low-gliss.mp3" autostart="true" hidden="true" loop="false">');
                    }
                }
				if($("#highLowApproachCheck").is(':checked')) {
                    if (OBVol[i][3] < OBVol[i][4] + parseFloat($("#highLowApproachVal").val()) ) {
                        $('embed').remove();
                        $('body').append('<embed src="sounds/sound01.mp3" autostart="true" hidden="true" loop="false">');
                    }
                }
				if($("#lowHighApproachCheck").is(':checked')) {
                    if (OBVol[i][3] > OBVol[i][4] - parseFloat($("#lowHighApproachVal").val())) {
                        $('embed').remove();
                        $('body').append('<embed src="sounds/beep03.mp3" autostart="true" hidden="true" loop="false">');
                    }
                }
                if($("#moveDownSoundCheck").is(':checked')) {
                    if(_expQueue.length > 0 && OBVol[i][3] - parseFloat($("#moveDownSoundVal").val()) > Math.min.apply(null, _expQueue)) {
                        $('embed').remove();
                        $('body').append('<embed src="sounds/sound07.mp3" autostart="true" hidden="true" loop="false">');
                    }
                }
                if($("#moveUpSoundCheck").is(':checked')) {
                    if(_expQueue.length > 0 && OBVol[i][3] + parseFloat($("#moveUpSoundVal").val()) < Math.max.apply(null, _expQueue)) {
                        $('embed').remove();
                        $('body').append('<embed src="sounds/fanfare01.mp3" autostart="true" hidden="true" loop="false">');
                    }
                }
				if (OBVol[i][3] > OBVol[i][4] * 1.05 ){//&& OBVol[i][4] > OBVol[i][1] * 1.01) {
					if(_isBelow && $("#crossAboveSoundCheck").is(':checked')) {
						$('embed').remove();
                        $('body').append('<embed src="sounds/sound07.mp3" autostart="true" hidden="true" loop="false">');
					}
					_isBelow = false;
					_isAbove = true;
				}
				if (OBVol[i][3] < OBVol[i][4] * 0.95  ){//&& OBVol[i][4] < OBVol[i][1] * 0.99) {
					if(_isAbove && $("#crossBelowSoundCheck").is(':checked')) {
                        $('embed').remove();
                        $('body').append('<embed src="sounds/fanfare01.mp3" autostart="true" hidden="true" loop="false">');
					}
					_isBelow = true;
					_isAbove = false;
				}
                _lastExp = OBVol[i][3];
                _lastLin = OBVol[i][4];
            }
            _chartObj.redraw();
        }
    }
}
function yLimitHandler() {
	yMax = parseFloat($("#maxVal").val());
	yAxis = _chartObj.yAxis[1];
	if($("#maxCheck").is(':checked') && !isNaN(yMax)) {
		yAxis.setExtremes(0, yMax, true, false);
	} else {
		yAxis.setExtremes(0, null, true, false);
	}
}