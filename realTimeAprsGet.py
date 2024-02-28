#!/home/pi/Ariadne/ariadne.venv/bin/python3

# !/usr/bin/env python3

"""
# The "on demand spotting" process requires to be make aware that an info request
# from whatever station has been raised (in a kind of "publish" / "subscribe" logic)
# in APRS network.
# In APRS this can be done raising a CQ request to an ANSRVR group (e.g. JS8CALL),
# by a message like 'CQ JS8CALL GATEWAY?'.
# Unforunately, for unknown reasons, the ANSRVR doesn't publish answers in form
# of APRS.FI "messages", but in form of raw packets.
# Viceversa, aprs.fi API doesn't allow (for unknown reasons) downloading row packets in bulk
# (api runs only for message, wx and position report).
# As consequence, we are forced to build a real-time never stopping daemon that runs continuosly
# for moving APRS messages directed to the gateway station in the database, in order to check
# the requests.

# This is a "message" :
# IU1IPB>APRS,TCPIP*,qAC,T2AUSTRIA::ANSRVR   :CQ JS8CALL GATEWAY?

# This is ANSRVR answer :
# IU1IPB>APWW11,qAO,KJ4ERJ-15::JS8CALL  :N:JS8CALL Ciao a tutti
# If info request message is received, the program publishs on APRRS
# answer as : gateway call, station locator, gateway email.
# It's also possible to ask via APRS if a remote js8cal station can be contacted.

"""

import calendar  # timestamp UTC
import configparser  # .ini configuration files library
import datetime  # date & time..
import logging  # log manager
import os
import re  # Regular expression library
import sqlite3  # sqlite3 database library
import sys
import time
import signal  # Catching system signal library

from datetime import datetime
from datetime import date
from pathlib import Path  # file path

import aprslib  # APRS library (not standard)

from socket import error as SocketError  # Managing connection error
import errno

# common functions

from common_functions import get_configuration  # lanscape parameters
from common_functions import check_qra
from common_functions import is_database_locked
from common_functions import send_msg_to_aprs

####

__author__ = "Ugo PODDINE, IU1IPB"
__copyright__ = "Copyright 2024"
__credits__ = ["Ugo PODDINE"]
__license__ = "GPL"
__version__ = "1.0.1"
__maintainer__ = "Ugo PODDINE"
__email__ = "iu1ipb@yahoo.com"
__status__ = "Beta"


###################


def signal_handler(sig, frame):

    # capturing CTRL+C gracefully

    #   print('You pressed Ctrl+C!')

    cursor_ariadne.close()
    logging.warning('> APRS receiver terminated gracefully.\n')
    sys.exit(0)

####################


def read_aprs():

    # Connect to aprs.fi and activate the aprs message
    # event driven call function to the callback function

    #    APRS = aprslib.IS("N0CALL")

    try:

        APRS = aprslib.IS(gateway_callsign)
        APRS.connect()

   # Trigger the callback realtime function
   # `raw`  or 'json'

        APRS.consumer(callback_aprs, raw=True)

    except ConnectionError as err:

        logging.warning('> APRS connection lost : ' + err)
        time.sleep(300)
        logging.warning('> Trying to restart after network failure...')

    return

#####################


def callback_aprs(packet):

# Main try clause, to trap the connection failures to aprs.is....

    try : 

    # Call back executed when new APRS message is received
    #    print (packet)

    # Check if a new registration on ANSVR group is required

        global before
        global now

        # Get now() time in UTC and convert to Epoch
        epoch_timestamp = calendar.timegm(time.gmtime())

        if before <= (epoch_timestamp - 43200):

# JS8CALL gateway that would like to answer over APRS must
# register itself on JS8CALL ANSRVR group (in MQTT logic : ANSRVR is the broker).
# This registration must be repeated twice a day, because it expires.
# But also in this way ANSRVR  sometime drops the subscription

            rc = send_msg_to_aprs(
                gateway_callsign,
                'ANSRVR',
                'J ' +
                gateway_announcement_ANSRVR_group)
#        rc = 0
            logging.warning(
                '> Gateway periodic keepalive registration on ANSRVR group : ' +
                gateway_announcement_ANSRVR_group)

            if rc == 0:

                before = epoch_timestamp

            else:

                before = epoch_timestamp + 1800  # wait 0,5 hour and try again


################

# The following packet structures are considered for extraction :
# IU1IPB>APWW11,qAO,KJ4ERJ-15::JS8CALL  :N:JS8CALL GATEWAY?
# IU1IPB>APWW11,qAO,KJ4ERJ-15::JS8CALL  :N:JS8CALL HEARING? IZ1BPS

        global cursor_ariadne

        packet = str(packet)
        packet = packet.upper()  # message in capital letters
        p = packet.find("::")
        if p == -1:

            return

        p = p + 2
        q = packet.find(':', p + 1)

        if q == -1:

            return

        dst = packet[p:q]
        dst = dst.strip()

        if dst == gateway_callsign:

            msg = packet[q + 1:-1]
            r = packet.find(">")
            srccall = packet[2:r]
            srccall = srccall.strip()
            logging.warning(
                "> APRS message from " +
                srccall +
                " to " +
                dst +
                " " +
                msg)

# For debug :
#        print("From : ",srccall, " to : ", dst, " ",msg)

# Inbound aprs message check....

            time_int = int(epoch_timestamp)  # Now... no better solution
            origin = 'IN'  # Origin APRS internet INFO
            from_email = ''  # email address vuoto
            request_string = msg[:18]
            message_id = time_int
            inbox_key = 0

# Managing the "Gateway" request : we announce to group that we are alive, with locator and email
# The request message, sent to ANSRVR, must have the folowing syntax : CQ <group name> GATEWAY?
# Sometime ANSRVR is less reliable than a MQTT broker....

            if request_string == ('N:' + gateway_announcement_ANSRVR_group + ' GATEWAY?') \
                    or request_string == ('N:' + gateway_announcement_ANSRVR_group + ':GATEWAY?'):

           # print(time_int, srccall, dst, message)

           # for avoiding spamming, max one request each 24h per QRA
                date_limit = epoch_timestamp - (24 * 3600)
                qra_no_ssid = srccall.split(SSID_SEPARATOR, 1)[0]
                params_ariadne = (date_limit, qra_no_ssid)
                rc = cursor_ariadne.execute(
                    "SELECT * FROM messages WHERE origin = 'IN' and status = 'INFO_REQUESTED' and time >= ? and srccall = ? ", params_ariadne)
                previous_request = cursor_ariadne.fetchall()
#            print ("PR = ",previous_request)

            # Request from APRS correct : we can answer...

                status = 'INFO_REQUESTED'

                if len(previous_request) == 0:

                    params_ariadne = (
                        message_id,
                        time_int,
                        srccall,
                        from_email,
                        dst,
                        msg,
                        inbox_key,
                        origin,
                        status)

            # blacklist on  aprs (es MAIL-2)
                    if srccall in banned_qra_aprs:

                        logging.error(
                            '> QRA ' + srccall + ' banned by aprs blacklist. ')

                        return

            # the request is added to message table ...

                    rc = cursor_ariadne.execute(
                        "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         params_ariadne)
                    connection_ariadne.commit()
                    logging.warning(
                        '> New gateway data request received from APRS.')

                # APRS message showing Locator and email address of the gateway station
                # is sent to APRS as answer of the request (that should be sent to ANSRVR
                # in form of : 'CQ JS8CALL Gateway?' Remember that the asking station must
                # be registered by ANSRVR sending a message 'J JS8CALL'

                    if gateway_email_address is None:

                        gateway_email_label = '<no email>'

                    else:

                        gateway_email_label = gateway_email_address.replace(
                            "@", "(at)")

                    info_message = "JS8CALL GATEWAY: " + gateway_locator + " " + gateway_email_label
#                print(srccall, " ", info_message)
                    rc = send_msg_to_aprs(gateway_callsign, srccall, info_message)
                    logging.warning(
                        '> Gateway info ready to be sent to : ' + srccall)

                    if rc != 0:

                        logging.error(
                            '> APRS connection lost : gateway request answer was not sent.')

# Managing the "Are you hearing <station>" request : we answer thar we are (or aren't) listen the requested station.
# Mesage, sent to ANSRVR, must have the folowing syntax : CQ <group name> <HEARING>? <CALLSIGN>,
# es CQ JS8CALL HEARING? IK1QQY

            elif request_string == ('N:' + gateway_announcement_ANSRVR_group + ' HEARING?') \
                    or request_string[0:18] == ('N:' + gateway_announcement_ANSRVR_group + ':HEARING?'):

                qra_requested = msg[19:]
                qra_requested = qra_requested.rstrip()

            # for avoiding spamming, max one request each 24h per QRA  and per
            # requested QRA
                date_limit = epoch_timestamp - (24 * 3600)

                qra_no_ssid = srccall.split(SSID_SEPARATOR, 1)[0]
                params_ariadne = (date_limit, qra_no_ssid, qra_requested)
                rc = cursor_ariadne.execute(
                    """SELECT * FROM messages WHERE origin = 'IN' and status = 'HEARING_REQUESTED'
                       and time >= ? and srccall = ? and dst = ?""", params_ariadne)

                previous_request = cursor_ariadne.fetchall()
#            print ("PR = ",previous_request)

            # Request from APRS correct : we can answer

                status = 'HEARING_REQUESTED'

                if len(previous_request) == 0:

                    params_ariadne = (
                        message_id,
                        time_int,
                        srccall,
                        from_email,
                        qra_requested,
                        msg,
                        inbox_key,
                        origin,
                        status)

            # blacklist on  aprs (es MAIL-2)
                    if srccall in banned_qra_aprs:

                        logging.error(
                            '> QRA ' + srccall + ' banned by aprs blacklist. ')

                        return

            # the request is insereted in message table ...

                    rc = cursor_ariadne.execute(
                        "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        params_ariadne)
                    connection_ariadne.commit()
                    logging.warning('> New hearing request received from APRS.')

             #  extracting the valid QSO from main QSOs table...

#                params_ariadne = (
# epoch_timestamp - station_alive_limit_hours * 3600, qra_requested)

                # Answer without horizon, like in email
                    params_ariadne = (0, qra_requested, gateway_callsign)

                    rc = cursor_ariadne.execute(
                        """SELECT qso.srccall, qso.frequency, qso.snr, Max(qso.time) as MaxTime FROM qso GROUP BY (qso.srccall)
                             HAVING qso.time > ? and qso.srccall = ? and qso.dst = ? ORDER BY (qso.time) DESC """,
                        params_ariadne)
                    heard = cursor_ariadne.fetchone()

                    if heard is None:

                        info_message = '> QRA : ' + qra_requested + \
                            ' is not heard by ' + gateway_callsign

                    else:

                        info_message = "> " + qra_requested + " HEARD BY " + gateway_callsign + " " \
                            + str(heard[1]) + " " + str(heard[2]) + " " +  \
                            datetime.utcfromtimestamp(
                                heard[3]).strftime("%d/%m/%y %H:%M")


#                print(info_message)
                    rc = send_msg_to_aprs(gateway_callsign, srccall, info_message)
#                rc = 0
                    logging.warning(
                        '> HEARD info ready to be sent to : ' + srccall)

                    if rc != 0:

                        logging.error(
                            '> APRS connection lost : gateway request answer was not sent.')

    except ConnectionError as err:

       logging.warning('> APRS connection lost : ' + err)
       time.sleep(300)
       logging.warning('> Trying to restart after network failure...')


       return

##############################

# Configuration


config = configparser.ConfigParser()  # .ini file manager

logging.basicConfig(filename='ariadne.log', encoding='utf-8', level=logging.WARNING,
                    format='%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')  # log file manager

##########################################################################
##
#  .ini file read settings
##

# Get configuration parameters from config.ini
configuration = get_configuration()

# Path js8call
js8call_db_path = configuration[1]
js8call_folder = configuration[0]

# Aprs.fi Key
api_key_aprsFi = configuration[2]

# JS8call station QRA (APRS to JS8CALL gateway)
gateway_callsign = configuration[3]

# Banned APRS callsign
banned_qra_aprs = configuration[6]
banned_qra_aprs = banned_qra_aprs.split(',')

# Whitlisted APRS callsign
whitelisted_qra_aprs = configuration[7]
whitelisted_qra_aprs = whitelisted_qra_aprs.split(',')

# Gateway Maidenhead Locator (short, format : CCnncc)
gateway_locator = configuration[16]

# Gateway (email to JS8CALL) station email addresss
gateway_email_address = configuration[15]

# Gateway APRS ANSRVR group name for publishing
# Subscription in MQTT logic
gateway_announcement_ANSRVR_group = configuration[21]

# Return number of hours during which a remote js8call station can be
# considered alive
station_alive_limit_hours = configuration[5]

#
SSID_SEPARATOR = '-'
# date_format = '%Y-%m-%d %H:%M:%S'

# Time flowing varaibles for registration
before = 0
now = 0

# Initializing log...
logging.warning('>>> Program : ' + os.path.basename(__file__) + ' started.')

# Initializing signal handling (for CTRL+C )
signal.signal(signal.SIGINT, signal_handler)

# Initializing signal handling (for program stop)
signal.signal(signal.SIGTERM, signal_handler)

##########################################################################

# The aprs valid info requests are imported in sqlite db table
# 1) only one "GATEWAY?" request each 24h for callsign
# 2) only one "HEARD?" request each 24h for callsign and requested callsign
# 2) only belonging to ANSVR answer format

####

##########################################################################

# Preliminary checks in db : are they locked ?

db = sqlite3.connect("ariadne.db3")
locked = is_database_locked(db)

if locked is True:

    logging.error('> Ariadne database is locked : aborted.')
    sys.exit(4)  # nothing can be done


############################

# Main program

################################

#  Main sqlite3 Ariadne db connected

connection_ariadne = sqlite3.connect("ariadne.db3")
cursor_ariadne = connection_ariadne.cursor()

# connection_ariadne= sqlite3.connect("aprs.db3:memory:?cache=shared") #
# In memory, to check

# Message table initialized if not present

cursor_ariadne.execute(
    """CREATE TABLE IF NOT EXISTS messages (messageId INTEGER PRIMARY KEY, time INTEGER, srccall TEXT,
        emailAddr TEXT, dst TEXT, message TEXT, inboxKey INTEGER, origin TEXT, status TEXT)""")

# Start aprs realtime message catching via callback function
rc = read_aprs()

# End of program (but it never ends)
cursor_ariadne.close()
logging.warning('> APRS gateway on demand spotting process ended.\n')
sys.exit()
