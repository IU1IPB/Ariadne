#!/home/pi/Ariadne/ariadne.venv/bin/python3

# !/usr/bin/env python3

"""
For each station received by js8call (QSO exchanged, *), the aprs.fi
database is checked. If an aprs messages directed to those stations can be found,
the messages are moved to the inbox/outbox folder of js8call for
subsequent forwarding (after @allcall msg? ).
Message duplication and lifecycle checks, spamming checks are made.
Feedback messages are sent back on aprs network.

"""

import calendar  # timestamp UTC
import configparser  # Configuration file manager
# import datetime  # time
import json  # json
import logging  # log manager
import os
import requests  # curl like
import sqlite3  # sqlite
import sys
import time

# from pathlib import Path  # Gestione path dei file
# from sqlite3 import OperationalError  # Errori database
from time import strftime  # libreria date
# from urllib.parse import quote  # Libreria urlencode semplificata


# Common functions
from common_functions import check_qra  # Check formal rightness callsign
from common_functions import get_configuration  # lanscape parameters
from common_functions import is_database_locked
from common_functions import send_msg_to_aprs
from common_functions import test_alive_ip_port  # Check connection (nmap)


#

__author__ = "Ugo PODDINE, IU1IPB"
__copyright__ = "Copyright 2024"
__credits__ = ["Ugo PODDINE"]
__license__ = "GPL"
__version__ = "1.0.1"
__maintainer__ = "Ugo PODDINE"
__email__ = "iu1ipb@yahoo.com"
__status__ = "Beta"

#

# Configuration

config = configparser.ConfigParser()  # .ini file manager

logging.basicConfig(filename='ariadne.log', encoding='utf-8', level=logging.WARNING,
                    format='%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')  # log file manager

##########################################################################
##
#  Reading configuration parameters from config.ini
##


# Read the blog field json template
t = open('modello.json', 'r')
modello_json = t.read()
t.close()

# Get configuration parameters from config.ini
configuration = get_configuration()

# Path js8call
js8call_db_path = configuration[1]

# Aprs.fi Key
api_key_aprsFi = configuration[2]

# JS8call station QRA (APRS to JS8CALL gateway)
gateway_callsign = configuration[3]

# Gateway Maidenhead Locator (short, format : CCnncc)
gateway_locator = configuration[16]

# Gateway (email to JS8CALL) station email addresss
gateway_email_address = configuration[15]

# Return number of days before message expiration
message_expiration_days = configuration[4]

# Return number of hours during which a remote js8call station can be
# considered alive
station_alive_limit_hours = configuration[5]

# Active radio stations are considered "alive" their last snr was greater than... db
# Too weak stations are not reliable.
station_alive_snr = configuration[19]

# Banned APRS callsign
banned_qra_aprs = configuration[6]
banned_qra_aprs = banned_qra_aprs.split(',')

# Banned js8call callsign
banned_qra_js8call = configuration[8]
banned_qra_js8call = banned_qra_js8call.split(',')

# Maximum number of pending messages allowed for each callsign
max_message_number = configuration[17]
# max_message_number = 3

# Get now() time in UTC and convert to Epoch
epoch_timestamp = calendar.timegm(time.gmtime())

SSID_SEPARATOR = '-'

# Initializing log...
logging.warning('>>> Program : ' + os.path.basename(__file__) + ' started.')

##########################################################################

# Preliminary check connection to internet (aprs.fi, aprs.is, db locks...)

ret = test_alive_ip_port("aprs.fi", 80)

if ret != 0:

    logging.error('no aprs.fi server connection : aborted.')
    sys.exit(4)  # nothing can be done


ret = test_alive_ip_port("aprs2.net", 80)

if ret != 0:

    logging.error('No aprs sending server connection : aborted.')
    sys.exit(4)  # nothing can be done

# Preliminary checks in db : are trhey locked ?

db = sqlite3.connect("ariadne.db3")
locked = is_database_locked(db)

if locked is True:

    logging.error('Ariadne database is locked : aborted.')
    sys.exit(4)  # nothing can be done


db = sqlite3.connect(js8call_db_path)
locked = is_database_locked(db)

if locked is True:

    logging.error('Js8call database is locked : aborted.')
    sys.exit(4)  # nothing can be done


################################

# Main sqlite3  Ariadne db connected

connection_ariadne = sqlite3.connect("ariadne.db3")
cursor_ariadne = connection_ariadne.cursor()

# Table messages initialized

cursor_ariadne.execute(
    """CREATE TABLE IF NOT EXISTS messages (messageId INTEGER PRIMARY KEY, time INTEGER, srccall TEXT,
        emailAddr TEXT, dst TEXT, message TEXT, inboxKey INTEGER, origin TEXT, status TEXT)""")

# Check if "heard" statistc tables exists and it's up-to-date

try:

    cursor_ariadne.execute("SELECT * from qso")

except sqlite3.OperationalError:

    print()
    print("ERROR : QSOs statistics not yet fed : please execute periodically creazioneStoricoQso.py")
    print()
    raise SystemExit


# Read,  from the statiscal database, the list of active callsign on the station
# Time limit for considering  "alive" a station

alive_limit = epoch_timestamp - station_alive_limit_hours * 3600

params_ariadne = (alive_limit, station_alive_snr, gateway_callsign)
alive = cursor_ariadne.execute(
    "SELECT DISTINCT srccall FROM qso WHERE time >= ? and snr >= ? and dst == ? ",
    params_ariadne)
alive = cursor_ariadne.fetchall()

# print(alive)

if alive is None:

    print()
    print("ERROR : no js8call station is received or statistics are obsolete.")
    print()
    sys.exit(4)

else:

    # For each active / heard *QRAs, check for APRS messages, in groups of 10 QRA...
    # WARNING : aprs.fi returns both messages destined for <QRA> and
    # those sent by <QRA>: only those sent must be filtered

    # Debug
    #    print (alive)
    #    alive = [('IU1IPB',), ('OM8KT',), ('M0KNC',), ('WE4SEL',)]

    ##########################################################################

    # Main grouping of 10 callsigns tuple cycle.... APRS.FI doesn't like
    # sinlgle call

    tt = [alive[i:i + 10] for i in range(0, len(alive), 10)]

# from list to string comma separated...
# : IU1IPB,OM8KT,M0KNC,WE4SEL

    for i in range(0, len(tt), 1):

        x = tt[i]
        x = str(x)
        x = x.replace("('", '')
        x = x.replace("',)", '')
        x = x.replace("]", '')
        x = x.replace("[", '')
        alive_for_aprs_fi = x.replace(" ", '')
#        print()
#        print(alive_for_aprs_fi)
#        print()


# Main aprs inbound message verification, for each "heard" station

#   aprs.fi requires inquiry by 10 callsigns

##########################################################################


# Wildcard *, useful for SSID management, it's not  supported by aprs.fi API

        aprs_connection_string = 'https://api.aprs.fi/api/get?what=msg&dst=' + \
            alive_for_aprs_fi + '&apikey=' + api_key_aprsFi + '&format=json'
#        print(connectionString)

        try:

            res = requests.get(
                aprs_connection_string, headers={
                    'Accept': 'application/json'})
            data = res.json()

        except requests.exceptions.RequestException as e:  # This is the correct syntax

            print("No internet connection : try again later !")
            raise SystemExit(e)


###


##########################################################################


# Read APRS message from json answer from aprs.fi

# Iterating through the json list
# cerca le righe messaggio nel json

# empty Aprs Header  {'command': 'get', 'result': 'ok', 'found': 0, 'what': 'msg', 'entries': []}
# error Aaprs message {'command': 'get', 'result': 'fail', 'code':
# 'ratelimit', 'description': 'query rate limited'}

        # result=data['messageid']
        t = list(data.values())
        status = t[1]
        num_msg = t[2]
        logging.warning(
            'Checked : ' +
            alive_for_aprs_fi +
            " " +
            status +
            " " +
            str(num_msg))

# check if the json is not empty and if th inquiry was successfull

        if data is not None and status == 'ok' and num_msg != '0':

            # Debug
            # print(data)
            # print(type(data))

            for i in data['entries']:

                # print(i)

                # fetch fields from aprs.fi json
                message_id = i['messageid']
                time_st = i['time']
                time_int = int(time_st)
                srccall = i['srccall']
                dst = i['dst']
                message = i['message']
                inbox_key = 0
                origin = 'AI'  # Origin APRS via internet
                status_init = 'RECEIVED'
                from_email = ''  # email address vuoto
                logging.warning(
                    "Checking record : " +
                    message_id +
                    " " +
                    time_st +
                    " " +
                    srccall +
                    " " +
                    dst +
                    " " +
                    message)

                # blacklist on  aprs (es MAIL-2)
                if srccall in banned_qra_aprs:

                    logging.error(
                        'QRA ' + srccall + ' banned by aprs blacklist. ')
                    continue

                # "From" callsign check not required : aprs special calls (e.g wx) can send message

                # if check_qra(
                # srccall) is False:  # Check formal correctness of "from" QRA.

                #    logging.error(
                #        'from QRA ' +
                #        srccall +
                #        ' is not a correct callsign. ')
                #    continue

                if check_qra(
                        dst) is False:    # Check formal correctness of "to" QRA, that will be sent on radio, mandatory

                    logging.error(
                        'to QRA ' + dst + ' is not a correct callsign. ')
                    continue

                # blacklist on HF callsign
                if dst in banned_qra_js8call:

                    logging.error(
                        'QRA ' + srccall + ' banned by js8call/HF blacklist. ')
                    continue

 #               print(i)


# Standard APRS ack request can not be managed. APRS.FI message API is not showing the request
# ack {xxxxx : ack request will always be sent, deducting it from the
# js8call inbox (js8call is disconnected); ack will be always send

# Finally, the message is moved to Ariadne main database

                params_ariadne = (
                    message_id,
                    time_int,
                    srccall,
                    from_email,
                    dst,
                    message,
                    inbox_key,
                    origin,
                    status_init)
                cursor_ariadne.execute(
                    "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    params_ariadne)

# Commit changes on db

            connection_ariadne.commit()
            logging.warning('APRS fetching terminated.')

# Cleaning..

del message_id, time_int, srccall, from_email, dst, message, inbox_key, origin, status_init, status, num_msg
del i, t

#############

# Check now if too many messages from the same callsign are pending
# transmission (e.g spamming, bad propagation)

params_ariadne = (max_message_number,)

#
query = """SELECT srccall, COUNT(messageId) AS CountOfQso FROM messages
           WHERE status = 'TRIGGERED' OR status = 'RECEIVED' and origin != 'IN' GROUP BY srccall HAVING CountOfQso > ?"""

rc = cursor_ariadne.execute(query, params_ariadne)
too_many_msg = cursor_ariadne.fetchall()
# print(too_much_msg)

# If too many messages are pending for the same callsign, the new ones
# must be scratched (APRS redoundancy or spamming)

for row in too_many_msg:

    #        print(row[0], row[1])
    qra_to_be_blocked = row[0]
    qra_to_be_blocked = qra_to_be_blocked.split(SSID_SEPARATOR, 1)[0]
    params_ariadne = (qra_to_be_blocked, )

    # List of orders to be refused
    rc = cursor_ariadne.execute(
        "SELECT messageId, time, srccall, dst FROM messages WHERE origin = 'AI' and status = 'RECEIVED' and srccall = ? ",
        params_ariadne)
    refused_orders = cursor_ariadne.fetchall()

    # Blocking orders
    rc = cursor_ariadne.execute(
        "UPDATE messages SET status = 'REFUSED' WHERE origin = 'AI' and status = 'RECEIVED' and srccall = ? ",
        params_ariadne)
    connection_ariadne.commit()

    logging.warning(
        "Too much pending messages for " +
        qra_to_be_blocked +
        " : they have been dropped.")

    # New APRS message is sent for making sender aware that its message has
    # been drpped

    for j in refused_orders:

        # Checked !! Do not change.

        dropped_message = "Msg JS8 UTC " + \
            strftime('%Y-%m-%d %H:%M:%S', time.gmtime(j[1])) + \
            " to:" + j[3] + " St:toomany"

        rc = send_msg_to_aprs(
            gateway_callsign,
            qra_to_be_blocked,
            dropped_message)

        if rc != 0:

            logging.error(
                'APRS connection lost : dropped message was not sent.')


##########################################################################

# Opening standard js8call database

####

# js8callFolder = Path("~/.local/share/JS8Call/")

js8call_db = sqlite3.connect(js8call_db_path)
cursor_js8call = js8call_db.cursor()

# Read all messages in js8call inbox / outbox .... why ??

# ? rows_js8call = cursor_js8call.execute("SELECT * FROM inbox_v1")

# Exploding json blog field

# ? for row in rows_js8call:
# ?    id = (row[0])
# ?    blob = (row[1])
# ?   data = json.loads(blob)

# ?    fr = (f'{data["params"]["FROM"]}')
#    print(fr, end=" ")
# ?    to = (f'{data["params"]["TO"]}')
#    print(to, end=" ")
# ?    utc = (f'{data["params"]["UTC"]}')
#    print(utc, end=" ")
# ?    id_internal = (f'{data["params"]["_ID"]}')
#    print(id_internal, end=" ")
# ?    text = (f'{data["params"]["TEXT"]}')
#    print(text)

##########################################################################


####

# This is the list of all newly arrived messages in the period, including
# duplicated ones.


rc = cursor_ariadne.execute(
    "SELECT messageId, time, inboxKey, srccall, emailAddr, dst, message, origin, status FROM messages WHERE origin = 'AI' and status = 'RECEIVED' ")
new = cursor_ariadne.fetchall()

# Try to group redoundant APRS messages, same text and arrived on a short
# time delay


# This is the list of all newly arrived messages, excluding duplication (same from qra, same to qra, same text) in the period
# This approach doesn't exclude duplication happened between two subsequent  program execution cycles.
# For this reason scheduling program execution each 10-15 minutes should be good.
# Findu seems to prevent duplication by its own (same message in almost 5
# minutes it's refused)

# No dupe selection

rc = cursor_ariadne.execute("""SELECT MIN(messages.messageId) AS minId, MIN(messages.time) AS minTime, MIN(messages.inboxKey) AS minInboxKey,
           messages.srccall, messages.emailAddr, messages.dst, messages.message,
           messages.origin, messages.status
           FROM messages GROUP BY messages.emailAddr, messages.dst, messages.message, messages.origin, messages.status
           HAVING messages.origin = 'AI' and  messages.status = 'RECEIVED' """)
new2 = cursor_ariadne.fetchall()

# Debug
# print ("Totale :")
# print (new)
# print
# print ("NO duplicazioni :")
# print (new2)


##########################################################################
##
#  Main messages insertion process into js8call inbox/outbox db, excuding duplication
##


for i in new2:  # No dupe !!

    # Read message database table and start filling js8call inbox

    message_id = i[0]
    time_int = int(i[1])
    srccall = i[3]
    dst = i[5]
    message = i[6]

# The js8call inbox table store the message in a json filled blob field
# We use a template for filling it correctly

    new_blob = json.loads(modello_json)
    f = new_blob["params"]["FROM"] = srccall
    f = new_blob["params"]["TO"] = dst
    f = new_blob["params"]["UTC"] = strftime(
        '%Y-%m-%d %H:%M:%S', time.gmtime(time_int))  # In UTC

# Js8call uses natively, as message _ID in blobfiield, a progressive number in microseconds from
# GMT: Wednesday 5 July 2017 23:59:59.999 = 1499299199999 Linux Epoch UTC

    f = new_blob["params"]["_ID"] = ((epoch_timestamp * 1000) - 1499299199999)
    f = new_blob["params"]["TEXT"] = message
    f = new_blob["params"]["PATH"] = gateway_callsign
    f = new_blob["params"]["DIAL"] = 0

    new_blob = json.dumps(new_blob)
#    print(new_blob)
#    print()
    # tupla ?  inbox_v1 key is a tuple: why ?

    params_js8call = (new_blob,)

# finally, the new message is set in the inbox / outbox of js8call..

    rc = cursor_js8call.execute(
        "INSERT INTO inbox_v1 (blob) VALUES (?)", params_js8call)
    js8call_db.commit()

# We ask database for the record unique key assigned to the new message..
    last_js8call_key = cursor_js8call.lastrowid

# .. in order to establish the relationship on the Ariadne message database.
# ... setting the status as "ready to be transmitted"..

    inbox_key = int(last_js8call_key)
    status = 'TRIGGERED'
    message_id = int(message_id)
    params_ariadne = (inbox_key, status, message_id)
#    print(params_ariadne)
    cursor_ariadne.execute(
        "UPDATE messages SET inboxKey = ?, status = ? WHERE messageId = ?",
        params_ariadne)

# ... all messages still in status RECEIVED and not put in TRIGGERED, are duplicated
# and can be set in this status.
# We mange here the aprs message duplication during the same ariadne run

    status_old = 'RECEIVED'
    status = 'DUPLICATED'

    params_ariadne = (status, status_old)

    cursor_ariadne.execute(
        "UPDATE messages SET status = ? WHERE status = ?",
        params_ariadne)

# In theory, duplication is still possible if the importing process starts in
# the middle of the APRS multi-path / redoundant transmission.
# A second check including also "triggered" messages is required, for
# cleaning inbox

# This is the list of all newly arrived messages in the period, including
# duplicated ones.

del new, new2

rc = cursor_ariadne.execute(

    "SELECT messageId, time, inboxKey, srccall, emailAddr, dst, message, origin, status FROM messages WHERE origin = 'AI' and status = 'TRIGGERED' ORDER BY time ASC ")

new = cursor_ariadne.fetchall()

##

rc = cursor_ariadne.execute("""SELECT MIN(messages.messageId) AS minId, MIN(messages.time) AS minTime, MIN(messages.inboxKey) AS minInboxKey,
           messages.srccall, messages.emailAddr, messages.dst, messages.message,
           messages.origin, messages.status
           FROM messages GROUP BY messages.emailAddr, messages.dst, messages.message, messages.origin, messages.status
           HAVING messages.origin = 'AI' and messages.status = 'TRIGGERED'   """)
new2 = cursor_ariadne.fetchall()

############################


# Studiare BENE !!

# From two dimensional lists, we extract the column 0 (messageId) // inboxKey
# era r[0]

x = list(range(len(new)))
x1 = [r[0] for r in new]
# print(x1)

y = list(range(len(new2)))
y1 = [r[0] for r in new2]
# print(y1)

# The duplicated messages are the ones not present in new2 SQL extraction

duplicated = list(set(x1) - set(y1))
# print(duplicated)

connection_ariadne.commit()

if duplicated is not None:

    for i in duplicated:

        params_ariadne = i

        rc = cursor_ariadne.execute(
            "SELECT inboxKey FROM messages WHERE messageId = ? ", (params_ariadne,))
        inbox_key = cursor_ariadne.fetchone()
        inbox_key = inbox_key[0]
#        print( i, inbox_key)
        logging.warning('Inbox duplication found : ' + str(inbox_key))


#  Physical deletion of duplicated messages from js8call inbox table...

        params_js8call = (inbox_key,)  # tupla ?
        rc = cursor_js8call.execute(
            "DELETE FROM inbox_v1 WHERE id = ?",
            params_js8call)
        js8call_db.commit()

# Logical deletion of duplicated messages from Ariadne messages table...

        params_ariadne = ('DUPLICATED', i)
        rc = cursor_ariadne.execute(
            "UPDATE messages SET status = ? WHERE messageId = ?",
            params_ariadne)


connection_ariadne.commit()
logging.warning('Main process ended.')


##########################################################################

# First service cycle : all messages, having aprs origin,  still not sent
# after the expiration limit, are deleted from inbox and marked as
# deleted in the Ariadne db

####

logging.warning('Expiration check process started.')

# expiring limit calculation
expiring_limit = epoch_timestamp - int(message_expiration_days) * 86400

expiring_limit = (expiring_limit,)

rc = cursor_ariadne.execute(
    "SELECT * FROM messages WHERE time < ? and origin == 'AI' and status = 'TRIGGERED'  ",
    expiring_limit)
expired = cursor_ariadne.fetchall()

for i in expired:

    # to be deleted message record detail

    message_id = i[0]
    time_st = i[1]
    time_int = int(time_st)
    srccall = i[2]
    dst = i[4]
    message = i[5]
    inbox_key = i[6]

#     test...
#
#     print(message_id, end=" ")
#     print(inbox_key, end=" ")
#     print(strftime('%Y-%m-%d %H:%M:%S', localtime(time_int)), end=" ")
#     print(message)


# Physical deletion of expired messages from js8call inbox table...

    params_js8call = (inbox_key,)  # tupla ?
    rc = cursor_js8call.execute(
        "DELETE FROM inbox_v1 WHERE id = ?", params_js8call)
    js8call_db.commit()

# Logical deletion of expired messages from Ariadne messages table...

    params_ariadne = ('EXPIRED', inbox_key)
    rc = cursor_ariadne.execute(
        "UPDATE messages SET status = ? WHERE inboxKey = ?",
        params_ariadne)
    connection_ariadne.commit()

# A new aprs message is sent back to the sender for making it aware
# that the message expired.

    exp_message = "Msg JS8 UTC " + \
        strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time_int)) + \
        " to:" + dst + " St: expired"

    logging.warning('Message : ' + str(inbox_key) + ' expired.')
    rc = send_msg_to_aprs(gateway_callsign, srccall, exp_message)

    if rc != 0:

        logging.error('APRS connection lost : exp message was not sent.')

logging.warning('Expiration check process ended.')

##########################################################################

# Second service cycle : all messages no more in the js8call inbox,
# have been deleted by the sysop. An aprs confirmation is sent back to the
# sender.

####

logging.warning('SYSOP dropping check process started.')

rc = cursor_ariadne.execute(
    "SELECT * FROM messages WHERE origin = 'AI' and status = 'TRIGGERED' ")
triggered = cursor_ariadne.fetchall()

for i in triggered:

    message_id = i[0]
    time_st = i[1]
    time_int = int(time_st)
    srccall = i[2]
    dst = i[4]
    message = i[5]
    inbox_key = i[6]


#     Per test...
#
#     print(inbox_key)

# If the record is no more in inbox...

    params_js8call = (inbox_key,)  # tupla ?
    rc = cursor_js8call.execute(
        "SELECT id FROM inbox_v1 WHERE id=?",
        params_js8call)
    missing = cursor_js8call.fetchone()
    # print(missing)
    if missing is None:

        # Marking the message as deleted..

        params_ariadne = ('DROPPED', inbox_key)
        rc = cursor_ariadne.execute(
            "UPDATE messages SET status = ? WHERE inboxKey = ?",
            params_ariadne)
        connection_ariadne.commit()

# ... and sending thw warning message to aprs

        ack_message = "Msg JS8 UTC " + \
            strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time_int)) + \
            " to:" + dst + " St: dropped"
        logging.warning(
            'Message : ' +
            str(inbox_key) +
            ' deleted by sysop.')
#        print (ack_message)
        rc = send_msg_to_aprs(gateway_callsign, srccall, ack_message)

        if rc != 0:

            logging.error('APRS connection lost : drop message was not sent.')

logging.warning('SYSOP dropping check process ended.')

##########################################################################

# xxxx service cycle : check on APRS network if someone asks for "js8call network"
# If yes, it publishs on APRRS gateway call, gateway email, station locator.
# This function has been moved to a neverednding daemon, see below.

####

# Current situation :

# The "on demand spotting" process requires to be make aware that an info request
# from whatever station has been raised (in a kind of "publish" / "subscribe" logic).
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


###

##########################################################################

# Third service cycle : all messages having status SENT in JS8CALL inbox table
# have been successfully delivered

####

logging.warning('Sent message check process started.')

rc = cursor_ariadne.execute(
    "SELECT * FROM messages WHERE origin = 'AI' and status = 'TRIGGERED' ")
triggered = cursor_ariadne.fetchall()

if triggered is not None:

    for i in triggered:

        message_id = i[0]
        time_int = int(i[1])
        srccall = i[2]
        dst = i[4]
        message = i[5]
        inbox_key = i[6]


# Check if the record is set as SENT in JS8CALL inbox...

        params_js8call = (inbox_key,)  # tupla ?

        rc = cursor_js8call.execute(
            "SELECT * FROM inbox_v1 where id = ?",
            params_js8call)

        maybe_sent = cursor_js8call.fetchone()

# Exploding json blog field..

        id = maybe_sent[0]
        blob = maybe_sent[1]
        data = json.loads(blob)

        fr = (f'{data["params"]["FROM"]}')
#        print(fr, end=" ")
        to = (f'{data["params"]["TO"]}')
#        print(to, end=" ")
        utc = (f'{data["params"]["UTC"]}')
#        print(utc, end=" ")
        id_internal = (f'{data["params"]["_ID"]}')
#        print(id_internal, end=" ")
        type = (f'{data["type"]}')
#        print(type)

        if type == 'DELIVERED':

            # Marking the message as SENT in Ariadne..

            params_ariadne = ('SENT', inbox_key)
            rc = cursor_ariadne.execute(
                "UPDATE messages SET status = ? WHERE inboxKey = ?",
                params_ariadne)
            connection_ariadne.commit()

# ... and sending an ack message to aprs

            ack_message = "Msg JS8 UTC " + \
                strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time_int)) + \
                " to:" + dst + " St: SENT"
            logging.warning(
                'Message : ' +
                str(inbox_key) +
                ' message has been sent by JS8call.')
#            print (ack_message)
            rc = send_msg_to_aprs(gateway_callsign, srccall, ack_message)

            if rc != 0:

                logging.error(
                    'APRS connection lost : ack message was not sent.')

logging.warning('Sent message check process ended.\n')

# Closing db connections
cursor_ariadne.close()
cursor_js8call.close()

sys.exit()
