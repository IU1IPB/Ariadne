#!/home/pi/Ariadne/ariadne.venv/bin/python3

# !/usr/bin/env python3


""" First step : it checks the js8call email folder. For each inbound waiting message, if
    the recipient call is present in the aprs or in the email callbook because it has already
    sent messages from aprs or email network. If yes, the message is forwarded to him throught
    the already used channel.
    The remote station should send a message to <gateway callsign> defined as :
    MSG TO:<final destination call> <message>
    Second step  : we answer to a remote station QUERY CALL <callsign>
    request via gateway. In this case no real time answer implemented, the message will be set in outbox
    and should be retrived with QUERY MSGS request.

"""

import calendar  # UTC timestamp
import configparser  # configuration files manager .ini
# import datetime  # time
# import email # imap library
# import email.utils # imap library
# import imaplib # main imap library
import json     # json manager
import logging  # log manager
import os
# import re  # Gestore regular expression
# import requests  # curl librray like
import sqlite3  # databse sqlite library
import sys
import time

# from email.header import decode_header
from pathlib import Path  # file path anager
from time import strftime  # date library

# Common functions

from common_functions import get_configuration  # lanscape parameters
# from common_functions import check_qra  # Check formal rightness callsign
from common_functions import send_simple_email
# from common_functions import test_alive_ip_port  # Check connection (nmap)
from common_functions import is_database_locked
# Simplified interface to send aprs messages 
from common_functions import send_msg_to_aprs


#

__author__ = "Ugo PODDINE, IU1IPB"
__copyright__ = "Copyright 2024"
__credits__ = ["Ugo PODDINE"]
__license__ = "GPL"
__version__ = "1.0.1"
__maintainer__ = "Ugo PODDINE"
__email__ = "iu1ipb@yahoo.com"
__status__ = "Beta"



# Configuration

config = configparser.ConfigParser()  # .ini file manager

logging.basicConfig(filename='ariadne.log', encoding='utf-8', level=logging.WARNING,
                    format='%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')  # log file manager


##########################################################################
##
#  Configuration settings
##

# Read the blog json model from file

t = open('modello.json', 'r')
modello_json = t.read()
t.close()

# Get configuration parameters from config.ini
configuration = get_configuration()

# Path js8call
js8_call_db_path = configuration[1]

# JS8call station QRA (APRS to JS8CALL gateway)
gateway_callsign = configuration[3]

# Gateway (email to JS8CALL) station email addresss
gateway_email_address = configuration[15]

# Return number of hours during which a remote js8call station can be
# considered alive
station_alive_limit_hours = configuration[5]

# Active radio stations are considered "alive" their last snr was greater than... db
# Too weak stations are not reliable.
station_alive_snr = configuration[19]

# Return number of days before message expiration
message_expiration_days = configuration[4]

# SMTP email account for outbound ack
smtp_username = configuration[12]
smtp_password = configuration[13]
smtp_server = configuration[14]

# Get now() time in UTC and convert to Epoch
epoch_timestamp = calendar.timegm(time.gmtime())

# get the alive stations into time horizon...
alive_limit = epoch_timestamp - station_alive_limit_hours * 3600

# Initializing log...
logging.warning('>>> Program : ' + os.path.basename(__file__) + ' started.')

##########################################################################

# Preliminary checks on db : are trhey locked ?

db = sqlite3.connect("ariadne.db3")
locked = is_database_locked(db)

if locked is True:

    logging.error('Ariadne database is locked : aborted.')
    sys.exit(4)  # nothing can be done


db = sqlite3.connect(js8_call_db_path)
locked = is_database_locked(db)

if locked is True:

    logging.error('Js8call database is locked : aborted.')
    sys.exit(4)  # nothing can be done


# Check if the messages database is there, if not, nothing to do


try:
    connection_ariadne = sqlite3.connect("ariadne.db3")

except sqlite3.OperationalError:

    print()
    print("ERROR : gateway messages database not present : nothing can be done !")
    print()
    raise SystemExit

cursor_ariadne = connection_ariadne.cursor()

try:
    cursor_ariadne.execute("SELECT * from messages")

except sqlite3.OperationalError:

    print()
    print("ERROR : gateway messages are not present : nothing can be done !")
    print()
    raise SystemExit


try:

    cursor_ariadne.execute("SELECT * from qso")

except sqlite3.OperationalError:

    print()
    print("ERROR : QSOs statistics not yet fed : please execute periodically creazioneStoricoQso.py")
    print()
    raise SystemExit


##########################################################################

# Js8call inbox database opened, all items are fetched

####

# js8call_folder = Path("~/.local/share/JS8Call/")

js8call_db = sqlite3.connect(js8_call_db_path)
cursor_js8call = js8call_db.cursor()
rc = cursor_js8call.execute('ATTACH DATABASE "ariadne.db3" AS ariadne')

# It extracts all js8call inbox messages not coming from aprs/email : a)
# manual messages b) messages sent from  remote stations in idle

rc = cursor_js8call.execute(
    """SELECT * FROM inbox_v1 LEFT JOIN ariadne.messages ON inbox_v1.id = ariadne.messages.inboxKey
       WHERE ((( ariadne.messages.inboxKey ) Is Null)) """)
rows_js8call = cursor_js8call.fetchall()

for row in rows_js8call:

    id = (row[0])
    blob = (row[1])
    data = json.loads(blob)

    # print (data)

    fr = (f'{data["params"]["FROM"]}')
    # print(fr, end=" ")
    to = (f'{data["params"]["TO"]}')
    # print(to, end=" ")
    utc = (f'{data["params"]["UTC"]}')
    # print(utc, end=" ")
    id_internal = (f'{data["params"]["_ID"]}')
    # print(id_internal, end=" ")
    text = (f'{data["params"]["TEXT"]}')


# The new exteranlly created messages are added to the main db messages table

####
    epoch = calendar.timegm(time.strptime(utc, '%Y-%m-%d %H:%M:%S'))
    status = "EXT_TRIGGERED"
    origin = "JS8"
    email_addr = ""

    params_ariadne = (
        id_internal,
        epoch,
        fr,
        email_addr,
        to,
        text,
        id,
        origin,
        status)

    cursor_ariadne.execute(
        "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        params_ariadne)
    connection_ariadne.commit()

    logging.warning(
        'External message added : ' +
        str(id_internal) +
        " " +
        str(id) +
        " " +
        origin)


##########################################################################

# Last heard station address (mail or aprs)...

alive_limit = epoch_timestamp - station_alive_limit_hours * 3600

params_ariadne = (alive_limit, 'JS8', 'IN')

rc = cursor_ariadne.execute(
    """SELECT messages.srccall, messages.origin, messages.emailAddr, Max(messages.time)
     as maxTime FROM messages GROUP BY (messages.srccall) HAVING messages.time >= ?
     and messages.origin != ? and messages.origin != ?  """, params_ariadne)

addr = cursor_ariadne.fetchall()

# x[0], x[1]....

# print("Addr = ",addr)

# List of not yet sent js8 externally created / inbound  messages

params_ariadne = (
    alive_limit,
    'JS8',
    "EXT_TRIGGERED")

rc = cursor_ariadne.execute(
    """SELECT messageId, inboxKey, origin, time, srccall, dst, message
       FROM messages WHERE time >= ? and origin == ? and status == ?""",
    params_ariadne)
radio_messages = cursor_ariadne.fetchall()

# Thanks to ChatGPT, we add the answer address to the messagge,
# taking in from the last arrived message from the same sender callsign

updated_messages = [
    (msg[0],
     msg[1],
     msg[2],
     msg[3],
     msg[4],
     msg[5],
     msg[6],
     a[1],
     a[2]) if msg[5] == a[0] else msg for msg in radio_messages for a in addr]

unique_messages = set([msg for msg in updated_messages if len(msg) > 6])

# FOR TEST February 2023

#for u in unique_messages:

#    if len(u) > 7:
#        print(u)


# Original "loop" address assignment. Naive.

# Search, if present, the aprs or email address of an inbound radio message
# j = message, x = potential address

for j in radio_messages:

    #    print(j[0], j[1], j[2], j[3], j[4], j[5])

    for x in addr:

        if x[0] == j[5]:  # addressing

            message_id = j[0]
            inbox_key = j[1]
            origin = x[1]
            message_date = j[3]
            js8_from = j[4]
            js8_dst = j[5]
            email_dst = x[2]
            message_text = j[6]

#            print ("Trovato :",j[0], j[1], j[2], j[3], j[4], j[5], " Addr :", x[0], x[1], x[2])
            logging.warning('Inbound message can be addressed : ' +
                            str(message_id) +
                            " " +
                            str(inbox_key) +
                            " " +
                            origin +
                            " " +
                            str(message_date) +
                            " fr: " +
                            js8_from +
                            " to: " +
                            js8_dst +
                            " " +
                            origin +
                            " " +
                            email_dst)

            # Each addressed message will be sent via APRS or email

            if origin == 'AI':  # APRS over internet

                # Perform the text split in part, for sending consegutive APRS
                # messages
                # max findu accepted aprs string lenght is 60 (APRS standard
                # 67); SMS total lenght is 160 ASCII
                # APRS string format is : [from callsign] > [message number] >
                # ... text ... { [item number]
                n = 38
                words = message_text.split(" ")
                lines = [words[0]]
                for word in words[1:]:

                    if len(lines[-1]) + len(word) < n:
                        lines[-1] += (" " + word)

                    else:
                        lines.append(word)

                 # Text formatting for messageID

                mi = "      " + str(inbox_key)
                mi = mi[len(mi) - 5:]

                nl = 0

                for z in lines:

                    # Text formatting for item number

                    nl = nl + 1
                    fi = "  " + str(nl)
                    fi = fi[len(fi) - 2:]

                # Building APRS message

                    aprs_msg = js8_from + ">" + mi + "> " + z + " {" + fi

#                    print (aprs_msg)

                # Send APRS messages

                    rc = send_msg_to_aprs(gateway_callsign, js8_dst, aprs_msg)

                    if rc != 0:

                        logging.warning(

                            'js8call inbound message transmission to APRS failed : I will try again later.')

                    else:

                      # if the aprs message was sent successfully, the message status is changed
                      # in any case, the message is not dropped from js8call
                      # mailbox till the end of the expiring period

                        params_ariadne = ("EXT_SENT", message_id)
                        cursor_ariadne.execute(
                            "UPDATE messages SET status = ? WHERE messageId = ?", params_ariadne)
                        logging.warning(
                            'Inbound js8call message ' +
                            str(message_id) +
                            ' correctly sent via APRS.')

            elif origin == 'IM':  # internet mail

                #  Forwarding js8call message to last heard callsign address

                mail_text = "Subject: Message received from " + js8_from + " through " + \
                    gateway_callsign + " Js8call gateway and forwarded to you. \n\n"
                mail_text = mail_text + "Message received on UTC : " + \
                    strftime(
                        '%Y-%m-%d %H:%M:%S',
                        time.gmtime(message_date)) + " from  " + js8_from + "\n\n"
                mail_text = mail_text + "<< " + message_text + " >>\n\n"
                mail_text = mail_text + "73, DE" + "\n" + gateway_callsign + "\n\n"
                mail_text = mail_text + \
                    "Please, DO NOT directly replay to this email. Answer format is different !"

                rc = send_simple_email(
                    smtp_server,
                    smtp_username,
                    smtp_password,
                    gateway_email_address,
                    email_dst,
                    mail_text)

                if rc != 0:

                    logging.error(
                        'SMTP server connection lost : inbound js8call message was not sent yet :' +
                        str(rc))

                else:

                    params_ariadne = ("EXT_SENT", message_id)
                    cursor_ariadne.execute(
                        "UPDATE messages SET status = ? WHERE messageId = ?", params_ariadne)
                    logging.warning(
                        'Inbound js8call message ' +
                        str(message_id) +
                        ' correctly sent via email.')

            else:

                logging.error('this situation is impossible ....')

#        else:

#            logging.warning('No internet or aprs addressing found')


connection_ariadne.commit()
logging.warning('Main process ended.')


##########################################################################

# First service cycle : all messages, having whatever origin, in inbox but
# still not sent back to aprs or email, after the expiration limit, are deleted from inbox and marked as
# deleted in the Ariadne db

####

logging.warning('Expiration check process started.')

# expiration linux time calculation
expiring_limit = epoch_timestamp - int(message_expiration_days) * 86400

# Debug
# expiring_limit = epoch_timestamp -int(1) * 86400

expiring_limit = (expiring_limit,)

expired = cursor_ariadne.execute(
    "SELECT * FROM messages WHERE time < ? and origin == 'JS8' and status = 'EXT_TRIGGERED'  ",
    expiring_limit)
expired = cursor_ariadne.fetchall()

for i in expired:

    # read to be dropped messages...

    message_id = i[0]
    time_st = i[1]
    time_int = int(time_st)
    srccall = i[2]
    email_addr = i[3]
    dst = i[4]
    message = i[5]
    inbox_key = i[6]

#     Per test...
#
#     print(message_id, end=" ")
#     print(inbox_key, end=" ")
#     print(strftime('%Y-%m-%d %H:%M:%S', localtime(time_int)), end=" ")
#     print(message)

    params_js8call = (inbox_key,)  # tupla ?

# physical deletion from the inbox of js8call...

    rc = cursor_js8call.execute(
        "DELETE FROM inbox_v1 WHERE id=?", params_js8call)
    js8call_db.commit()

# ... logical deletion from Ariadne database...

    params_aprs = ('EXT_EXPIRED', inbox_key)
    rc = cursor_ariadne.execute(
        "UPDATE messages SET status = ? WHERE inboxKey = ?",
        params_aprs)
    logging.warning('Physically deleted inbound message :' +
                    str(message_id) + " " + str(inbox_key))


###

connection_ariadne.commit()
logging.warning('Expiration check process.')

# Closing db connections
#cursor_ariadne.close()
#cursor_js8call.close()

#sys.exit()


### At the moment duplication logic issue !!! Nor running

#########################################################################

# Second service cycle : messages coming from radio station, directed to @ALLCALL
# with text QUERY CALL <callsign>, should be answered if the
# request callsign can be reached by gateway station via aprs or email
# Answer must be solecited sending to @ALLCALL a QUERY MSGS request (no real time answer) 

####

logging.warning('QUERY CALL check process started.')

# Seraching recent @ALLCALL QUERY MSGS requests...

params_ariadne = (

    epoch_timestamp - station_alive_limit_hours * 3600,
	'@ALLCALL')

rc = cursor_ariadne.execute("SELECT * FROM qso WHERE time >= ? AND dst = ?", params_ariadne)

query_msgs = cursor_ariadne.fetchall()

#  checking each recent @ALLCALL request...

for i in query_msgs :

    text = i[6]
    srccall = i[4]
 
    if text[0:11] == ' QUERY CALL' :   ## poi togliere lo spazio, diventa [0:10] e text[11:t]

        t = text.find("?")
        requested_callsign = text[12:t]

# Searching if the requested station (form @ALLCALL QUERY CALL) has been recently heard on aprs or email...
# Degining "recently" as station_alive_limit_hours.. compromise.

        params_ariadne = (epoch_timestamp - station_alive_limit_hours * 3600, requested_callsign)

        rc = cursor_ariadne.execute(
            """SELECT messages.srccall, Max(messages.time) as MaxTime, messages.origin FROM messages GROUP BY (messages.srccall)
            HAVING messages.time >= ? and messages.srccall == ? and (messages.origin = 'AI' or messages.origin = 'IM') """, params_ariadne)

        received = cursor_ariadne.fetchone()
 
# ... if yes, the answer message could be built (according to the js8call style) and put into inbox for later retrive,
# .... if not duplicated...

        if received is not None :

# Checking for already triggered answers... 
# In practice one answer per question per expiration period, no more...

            if received[2] == 'AI' :

                internet_origin = 'APRS'

            else :

                internet_origin = 'EMAIL'

            message = 'YES, ' + requested_callsign + ' VIA ' + internet_origin

            params_ariadne = (epoch_timestamp - station_alive_limit_hours * 3600, gateway_callsign, srccall, message )

            rc = cursor_ariadne.execute(

             """SELECT * FROM messages WHERE time >= ? AND srccall = ? AND dst = ? AND message = ? AND origin = 'JS8' AND \
                 (status = 'EXT_TRIGGERED' or status = 'EXT_SENT') """, params_ariadne)

            to_be_checked = cursor_ariadne.fetchone()

# if we have already set the answer in the inbox (same destination station, same answer, during the alive period, not sent status...),
# nothing to do more....

            if to_be_checked is not None :

                continue

# We found a recent aprs or email request not duplicated for the requested station : we can trigger an answer (in inbox, not realtime)
# for the requesting js8call remote radio station....

#  .. first of all we prepare the ariadne database record, without writing it.


#            print (epoch_timestamp, " ", gateway_callsign, " ", srccall," ", message)

            message_id = ((epoch_timestamp * 1000) - 1499299199999)
            time_int = epoch_timestamp
            from_email = ''
            dst = srccall
            inbox_key = 0
            origin = 'JS8'
            status = 'EXT_TRIGGERED'

# ... than we prepare and wait the js9call inbox...
# The js8call inbox table store the message in a json filled blob field :
# we use a template for filling it correctly.

            new_blob = json.loads(modello_json)
            f = new_blob["params"]["FROM"] = gateway_callsign
            f = new_blob["params"]["TO"] = srccall
            f = new_blob["params"]["UTC"] = strftime(
                '%Y-%m-%d %H:%M:%S', time.gmtime(epoch_timestamp))  # In UTC

# Js8call uses natively, as message _ID in blobfiield, a progressive number in microseconds from
# GMT: Wednesday 5 July 2017 23:59:59.999 = 1499299199999 Linux Epoch UTC

            f = new_blob["params"]["_ID"] = ((epoch_timestamp * 1000) - 1499299199999)
            f = new_blob["params"]["TEXT"] = message
            f = new_blob["params"]["PATH"] = gateway_callsign
            f = new_blob["params"]["DIAL"] = 0

            new_blob = json.dumps(new_blob)
            params_js8call = (new_blob,)

# ... the new message is set in the inbox / outbox of js8call..

            rc = cursor_js8call.execute(
                "INSERT INTO inbox_v1 (blob) VALUES (?)", params_js8call)
            js8call_db.commit()

# We ask js8call database for the record unique key assigned to the new message..

            last_js8call_key = cursor_js8call.lastrowid

# ... we can finally write the Ariadne database, with the js8call_key..

            params_ariadne = (

                message_id,
                time_int,
                gateway_callsign,
                from_email,
                dst,
                message,
                last_js8call_key,
                origin,
                status )

#            print (params_ariadne)

            cursor_ariadne.execute(

                "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                params_ariadne)
 
            connection_ariadne.commit()
            logging.warning('Answer QUERY CALL set in inbox : ' + str(message_id))


logging.warning('QUERY CALL check process ended.\n')


# Closing db connections
cursor_ariadne.close()
cursor_js8call.close()

sys.exit()
