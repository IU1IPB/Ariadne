#!/home/pi/Ariadne/ariadne.venv/bin/python3

# !/usr/bin/env python3

"""
For each station received by js8call (QSO exchanged, *) or without filter, the
program checks smtp email folder associated to the gateway (e.g. yahoo, hotmail...).
If an email  message directed to the gateway email address carrying a message
directed to js8call remote station, can be found, the messages is moved to
the inbox/outbox folder of js8call for subsequent forwarding (after @allcall msg? ).
Message duplication and lifecycle checks, spamming checks are made.
Feedback email is sent back to the original email sender.
The email must have in the subject (email text is ignored) :

  JS8CALL FROM:< QRA> TO:<QRA> MSG:<Testo messaggio> (max 160 chars)

for sending the message, or :

  JS8CALL HEARING?

... for receiving the "HEARD" list.

"""


import calendar  # For UTC timestamp
import configparser  # Standard configuration .ini file manager
import email  # imap libraries
import email.utils  # imap libraries
import html  # HTML library (for "HERARD" email)
import imaplib  # main imap libraries
import json     # Libreria gesione dei json
import logging  # log manager
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import sqlite3  # Libreria sqlite
import sys
import time

from email.header import decode_header
from time import strftime  # date library

# Common functions
from common_functions import get_configuration  # landscape parameters .ini
from common_functions import check_qra  # Check formal rightness callsign
from common_functions import send_simple_email  # send smtp email
from common_functions import test_alive_ip_port  # Check connection (nmap)
from common_functions import is_database_locked  # Check db availability

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

logging.basicConfig(filename='ariadne.log', encoding='utf-8', level=logging.WARNING,
                    format='%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')  # log file manager

config = configparser.ConfigParser()

##########################################################################
##
#  Parameters definition / lanscape
##

# JS8CALL "blog" database json field model for inbox/outbox

t = open('modello.json', 'r')
modello_json = t.read()
t.close()

# Get configuration parameters from config.ini
configuration = get_configuration()

# js8call path
js8_call_db_path = configuration[1]

# Aprs.fi Key
api_key_aprs = configuration[2]

# JS8call station QRA (APRS to JS8CALL gateway)
gateway_callsign = configuration[3]

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

# Whitlisted APRS callsign
whitelisted_qra_aprs = configuration[7]
whitelisted_qra_aprs = whitelisted_qra_aprs.split(',')

# Banned js8call callsign
banned_qra_js8call = configuration[8]
banned_qra_js8call = banned_qra_js8call.split(',')

# IMAP gateway email folder to be checked
imap_username = configuration[9]
imap_password = configuration[10]
imap_server = configuration[11]

# SMTP gateway email folder for sending answers
smtp_username = configuration[12]
smtp_password = configuration[13]
smtp_server = configuration[14]

# Maximum number of pending messages allowed for each callsign
max_message_number = configuration[17]

# When message from email is received, check if the
# destination station is in "heard" list (True / False)
email_check_dst_heard = configuration[18]

# Get now() time in UTC and convert to Epoch
epoch_timestamp = calendar.timegm(time.gmtime())

# get the alive stations into time horizon...
alive_limit = epoch_timestamp - station_alive_limit_hours * 3600

# Initializing log...
logging.warning('>> Program : ' + os.path.basename(__file__) + ' started.')

########################################################

# Preliminary checks on db : are they locked ?

rc = sqlite3.connect("ariadne.db3")
locked = is_database_locked(rc)

if locked is True:

    logging.error('Ariadne database is locked : aborted.')
    sys.exit(4)  # nothing can be done

rc = sqlite3.connect(js8_call_db_path)
locked = is_database_locked(rc)

if locked is True:

    logging.error('Js8call database is locked : aborted.')
    sys.exit(4)  # nothing can be done


# Create or open the main database

connection_ariadne = sqlite3.connect("ariadne.db3")
cursor_ariadne = connection_ariadne.cursor()

# Check if "heard" statistics are up-to-date

params_ariadne = (alive_limit,)
rc = cursor_ariadne.execute(
    "SELECT DISTINCT srccall FROM qso WHERE time >= ? ",
    params_ariadne)
alive = cursor_ariadne.fetchall()

if alive is None:

    print()
    print("ERROR : no js8call station is received or statistics are obsolete.")
    print()
    sys.exit(4)

##########################################################################

# Main Ariadne database initialization

rc = cursor_ariadne.execute(
    """CREATE TABLE IF NOT EXISTS messages (messageId INTEGER PRIMARY KEY, time INTEGER, srccall TEXT,
        emailAddr TEXT, dst TEXT, message TEXT, inboxKey INTEGER, origin TEXT, status TEXT)""")


##########################################################################

# Read the inbound email messages and check if someone has 'Subject JS8CALL'

# Check  connection to email provider : imap

ret = test_alive_ip_port(imap_server, 993)

if ret != 0:

    logging.error('no IMAP server connection : aborted.')
    sys.exit(4)  # nothing can be done


# Check  connection to email provider : smtp

ret = test_alive_ip_port(smtp_server, 465)

if ret != 0:

    logging.error('no SMTP server connection : aborted.')
    sys.exit(4)  # nothing can be done


# create an IMAP4 class with SSL
imap = imaplib.IMAP4_SSL(imap_server)

# authenticate on IMAP folder

try:

    imap.login(imap_username, imap_password)

except imaplib.IMAP4.error as e:

    logging.error("IMAP server connection failed : aborted with = " + str(e))
    sys.exit(4)

# Open the INBOX email folder...
status, messages = imap.select("INBOX")

# ... read only the "unread" messages...
retcode, unseen = imap.search(None, '(UNSEEN)')

if retcode == 'OK':

    unseen = unseen[0].decode('utf-8').split()
    unseen_index = [int(valore) for valore in unseen]

    for i in unseen_index[::-1]:

        # fetch the email message by Id
        # res, msg = imap.fetch(str(i), "(RFC822)")

        # Read some header fields from email without marking it ad "read";
        # Normal email can be mixed to Ariadne managed email.
        res, msg = imap.fetch(
            str(i), '(BODY.PEEK[HEADER.FIELDS (From To Subject date Message-ID)])')

        if msg is not None:

            for response in msg:

                if isinstance(response, tuple):
                    # parse a bytes email into a message object
                    # msg = email.message_from_bytes(response[1])
                    msg: email.message.Message = email.message_from_bytes(
                        response[1])  # chatGpt suggestion for avoiding plyint error
#                            print(msg)
                    # decode the email subject
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        # if it's a bytes, decode to str
                        subject = subject.decode(encoding)
                        # message max lenght like SMS, 160 chars
                        subject = subject[0:199]
                    # decode email sender
                    from_email, encoding = decode_header(msg.get("From"))[0]
                    if isinstance(from_email, bytes):
                        from_email = from_email.decode(encoding)
                    # decode email date
                    date, encoding = decode_header(msg.get("date"))[0]
                    if isinstance(date, bytes):
                        date = date.decode(encoding)
                    localdate = email.utils.parsedate_to_datetime(date)

                    # epoch = calendar.timegm(
                    #    localdate.timetuple())  # Linux epoch in UTC

                    # Check email Subject for finding "JS8CALL:"...

                    mode = subject[0:7]

                    if mode == 'JS8CALL':

                        # Find position of string 'MSG:' in the subject
                        m = subject.find('MSG:')

                        # If bot found, can be "HEARD" request or malformed
                        # message...
                        if m != -1:

                            # Extarct the MSG text, clean it by not standard \n
                            # put there by Office365...

                            m = m + 4
                            text = subject[m:(m + 67)]
                            ''.join(text.splitlines())

                            # Remove spaces from string (keypunching errors)
                            # from. Now position in string is fixed.

                            x = subject[0:(m - 4)]
                            x = x.replace(" ", "")

                            # FROM is now at 12, the TO depends on QRA lenght,
                            # variable

                            f = 12
                            t = x.find('TO:') + 3
                            srccall = (x[f:(t - 3)]).rstrip()

                            # ... find TO

                            dst = x[t:(m - 4)]

                            # blacklist silently on sender callsigns on aprs
                            # (es MAIL-2)

                            if srccall in banned_qra_aprs:

                                logging.error(
                                    'QRA ' + srccall + ' banned by aprs blacklist. ')

                             # The email is finally set as "read", tnx to
                             # chatGPT..

                                imap.store(str(i), '+FLAGS', '(\\Seen)')

                                continue

                             # Check if the destination QRA, that will be sent on radio, is correct
                             # according to validation rules

                            if check_qra(
                                    dst) == False:  # QRA of message not correct

                                logging.warning(
                                    'The station QRA ' + dst + ' is not correct : message refused.')

                              # Building "contact impossible" email
                              # message :

                                m = "Subject: Js8call message refused : the destination QRA seems not to be a valid callsign. \n\n"
                                m = m + "Your message of UTC " + \
                                    strftime(
                                        '%Y-%m-%d %H:%M:%S',
                                        time.gmtime(epoch_timestamp)) + " to " + dst + " was refused." + "\n\n"
                                m = m + "<< " + subject + \
                                    " >>\n\nThis message was generated by the mail2js8call gateway. Please, do not answer."
                                m = m + "\n73\n" + gateway_callsign

                               # Sending not valid callsign email

                                rc = send_simple_email(
                                    smtp_server,
                                    smtp_username,
                                    smtp_password,
                                    gateway_email_address,
                                    from_email,
                                    m)

                                logging.warning(
                                    'The callsign ' + dst + ' is incorrect : message refused.')

                                if rc != 0:

                                    logging.error(

                                        'SMTP server connection lost : invalid callsign message was not sent.')

                            # The email is set as "read", tnx to chatGPT..

                                imap.store(str(i), '+FLAGS', '(\\Seen)')

                                continue

                            # blacklist silently on HF callsign

                            if dst in banned_qra_js8call:

                                logging.error(
                                    'QRA ' + srccall + ' banned by js8call/HF blacklist. ')
                                continue

                            # The email is set as "read", tnx to chatGPT..
                            imap.store(str(i), '+FLAGS', '(\\Seen)')

                            # IDmessaggio is UTC timestamp for email messages

                            message_id = int(epoch_timestamp)

                            # Message finally marked as "read", tnx to ChatGPT
                            imap.store(str(i), '+FLAGS', '(\\Seen)')


##########################################################################

# Check if the to / dst station can be contacted : first step should always be
# belonging to heartbeat network ....

                            frequency = 7.078  # MHz ; If the "heard" check it's not active, this is the default

                            # If the "heard" chech is enforced also for email
                            # messages..

                            if email_check_dst_heard is True:

                                # get the alive stations into time horizon...
                                # credits to ChatGPT.

                                params_ariadne = (
                                    alive_limit, station_alive_snr, dst, gateway_callsign)
                                rc = cursor_ariadne.execute(
                                    """SELECT qso.* FROM qso JOIN (
                                          SELECT MAX(time) AS maxTime, srccall
                                          FROM qso
                                          WHERE time >= ? AND snr >= ? AND srccall == ? and dst == ?
                                          GROUP BY srccall
                                          ) AS maxTimeTable
                                          ON qso.time = maxTimeTable.maxTime AND
                                          qso.srccall = maxTimeTable.srccall""", params_ariadne)

# Old SQL w/out frequency       "SELECT DISTINCT srccall FROM qso WHERE
# time >= ? and snr >= ? and srccall = ? ",

                                alive = cursor_ariadne.fetchone()
                                # print (alive)

                                # The station can not be realistically
                                # connected...

                                if alive is None:

                                    logging.warning(
                                        'The station ' + dst + ' cannot be contacted : message refused.')

                                   # Building "contact impossible" email
                                   # message :

                                    m = "Subject: Js8call message refused : the destination station can not be contacted. \n\n"
                                    m = m + "Your message of UTC " + \
                                        strftime(
                                            '%Y-%m-%d %H:%M:%S',
                                            time.gmtime(epoch_timestamp)) + " to " + dst + " was deleted." + "\n\n"
                                    m = m + "<< " + subject + " >>\n\n"
                                    m = m + "Your message was refused because, during the last " + \
                                        str(station_alive_limit_hours) + " hours, " + dst + \
                                        " could not be contacted.\n\nThis message was generated by the mail2js8call gateway. Please, do not answer."
                                    m = m + "\n73\n" + gateway_callsign

                                   # Sending email

                                    rc = send_simple_email(
                                        smtp_server,
                                        smtp_username,
                                        smtp_password,
                                        gateway_email_address,
                                        from_email,
                                        m)

                                    if rc != 0:

                                        logging.error(

                                            'SMTP server connection lost : dropped message was not sent.')
                                else:

                                    frequency = alive[1]
                                    # print (frequency)

# If the station can be connected and the message is not yet there, new
# message item is added to messages table

                            status_init = 'RECEIVED'
                            origin = 'IM'  # Internet mail

                            inbox_key = 0

                            params_ariadne = (
                                message_id,
                                epoch_timestamp,
                                srccall,
                                from_email,
                                dst,
                                text,
                                inbox_key,
                                origin,
                                status_init)
                            cursor_ariadne.execute(
                                "INSERT OR IGNORE INTO messages VALUES  (?, ?, ?, ?, ?, ?, ?, ?, ?)", params_ariadne)

# Changes are committed on database

                            connection_ariadne.commit()


##########################################################################

# Building the "HEARD?" answe Request message is JS8CALL HEARING? or JS8CALL:HEARING?.
# Complex, HTML

# Check if it's a well formed  "HEARD" (HEARING?) request...

                        x = subject.find('HEARING?')
#                                 print(m)
                        if x != -1:  # Malformed JS8CALL email request....

                            logging.warning(
                                'HEARING? message received : building answer.')

                            #  extracting the valid QSO from main QSOs table...

                            params_ariadne = (
                                epoch_timestamp - station_alive_limit_hours * 3600, station_alive_snr, gateway_callsign)
                            rc = cursor_ariadne.execute(
                                """SELECT qso.srccall, qso.frequency, qso.snr, Max(qso.time) as MaxTime FROM qso GROUP BY (qso.srccall)
                                   HAVING qso.time > ? and qso.snr >= ? and qso.dst == ? ORDER BY (qso.time) DESC """,
                                params_ariadne)

                            heard = cursor_ariadne.fetchall()


######################

                            # build the text version of the email

                            m = "Subject: JS8CALL stations heard during the last " + \
                                str(station_alive_limit_hours) + " hours by " + \
                                gateway_callsign + " gateway. \n\n"

                            m = m + "This message was automatically generated, after your request, by mail2js8call gateway. Please, do not answer. \n"
                            m = m + "Please consider that only stations having last HB snr greater or equal than " + \
                                str(station_alive_snr) + \
                                " db are considered reliable.\n\n"

                            # Empty answer : Text version..

                            if heard == -1 or len(heard) == 0:  # Nothing heard

                                m = m + \
                                    ("No js8call station was received.") + "\n"

                                m = m + "\n" + "73, DE" + "\n" + gateway_callsign

                                email_text_text = m

                           # Empty answer : HTML version

                                email_text_html = """\
                                        <html>
                                         <head></head>
                                         <body>
                                           <p><br>
                                              No js8call station was received. </p>
                                         </body>
                                             <p><br>
                                              73, DE <br>""" \
                                              + gateway_callsign + """</p>
                                          </table>
                                        </html>
                                        """

                            else:

                                for j in heard:

                                    # "HEARD" Text version..

                                    # Extracts and format in text table format
                                    # the list of heard stations

                                    text_item = j[0].ljust(
                                        12)  # QRA in 10 spazi
                                    text_item = text_item + " Freq:  " + str(j[1]) + "\t Snr: " + str(
                                        j[2]) + "\t UTC time: " + strftime('%Y-%m-%d %H:%M:%S', time.gmtime(j[3]))
                                    m = m + text_item + '\t\n'

                                    m = m + "\n" + "73, DE" + "\n" + gateway_callsign

                                    email_text_text = m

###########################################

                           # ..... "HEARD" HTML version of the email message...

                           # format the data table in HTML...

                            # List header..
                                intestazione = "QRA\tFrequency\tsNR\tUTC time\n"

                            # HTML table structure
                                corpo_tabella = ""

                                for j in heard:

                                    #  filling the HTML table

                                    corpo_tabella += f"{j[0]}\t{j[1]}\t{j[2]}\t{strftime('%Y-%m-%d %H:%M:%S', time.gmtime(j[3]))}\n"

                            # HTML formatting header

                                html_tabella = "<table style='width:100%; border-collapse: collapse;'>"

                            # filling header...
                                colonne_intestazione = intestazione.strip().split('\t')
                                html_tabella += "<tr>" + \
                                    "".join(
                                        f"<th style='text-align: left;'>{html.escape(colonna)}</th>" for colonna in colonne_intestazione) + "</tr>"

                           # fillimg items

                                righe_dati = corpo_tabella.strip().split('\n')

                                for riga in righe_dati:

                                    colonne_riga = riga.split('\t')
                                    html_tabella += "<tr>" + \
                                        "".join(
                                            f"<td>{html.escape(col)}</td>" for col in colonne_riga) + "</tr>"

                                html_tabella += "</table>"

                           # Text of the message

                                email_text_html = """\
                                            <html>
                                             <head></head>
                                             <body>
                                           <p><br>
                                                  This message was automatically generated, after your request, by mail2js8call gateway. Please, do not answer.
                                           <br>
                                                  Please consider that only stations having last HB snr greater or equal than """ + str(station_alive_snr)

                                email_text_html = email_text_html + """ db are considered reliable.
                                           </p>
                                             </body>"""

                                email_text_html = email_text_html + html_tabella
                                email_text_html = email_text_html + """\
                                                 <p><br>
                                                  73, DE <br>""" \
                                                  + gateway_callsign + """</p>
                                              </table>
                                            </html>
                                            """

#############################

                            # Create message container and prepare to send (
                            # the correct MIME type is multipart/alternative).

                            msg = MIMEMultipart('alternative')
                            msg['Subject'] = "Subject: JS8CALL stations heard during the last " + str(station_alive_limit_hours) + " hours by " + \
                                gateway_callsign + " gateway. \n\n"

                            msg['From'] = gateway_email_address
                            msg['To'] = from_email

                            # Record the MIME types of both parts - text/plain
                            # and text/html.
                            part1 = MIMEText(email_text_text, 'plain')
                            part2 = MIMEText(email_text_html, 'html')

                            # Attach parts into message container.
                            # According to RFC 2046, the last part of a multipart message, in this case
                            # the HTML message, is best and preferred.
                            msg.attach(part1)
                            msg.attach(part2)

                            # print(part2)
#############################################################################

                            # Send "heard" e mail
                            msg = msg.as_string()  # Mandatory for MIME messages
#                            print(m)
#                            print (from_email)
                            rc = send_simple_email(
                                smtp_server,
                                smtp_username,
                                smtp_password,
                                gateway_email_address,
                                from_email,
                                msg)

                            if rc != 0:

                                logging.error(

                                    'SMTP server connection lost : heard message was not sent :' + str(t))

                            else:

                                # Grazie a chatGPT, marco il messaggio di
                                # richiesta "HEARD" come letto
                                imap.store(str(i), '+FLAGS', '(\\Seen)')
                                logging.warning(
                                    'HEARING? message correctly sent.')


########

# Check now if too many messages from the same callsign are still pending
# transmission (e.g spamming)

params_ariadne = (max_message_number,)

query = """SELECT srccall, COUNT(messageId) AS CountOfQso FROM messages WHERE
           status = 'TRIGGERED' OR status = 'RECEIVED' and origin != 'IN' GROUP BY srccall HAVING CountOfQso > ?"""

rc = cursor_ariadne.execute(query, params_ariadne)
too_much_msg = cursor_ariadne.fetchall()
# print(too_much_msg)

# If too much messages are pending for the same callsign, the new ones
# must be scratched (APRS redoundancy or spamming)

for row in too_much_msg:

    #        print(row[0], row[1])
    qra_to_be_blocked = row[0]
    ssid_separator = "-"
    qra_to_be_blocked = qra_to_be_blocked.split(ssid_separator, 1)[0]
    params_ariadne = (qra_to_be_blocked, )

    # List of orders to be refused
    rc = cursor_ariadne.execute(
        """SELECT messageId, time, srccall, emailAddr, message
          FROM messages WHERE origin = 'IM' and status = 'RECEIVED' and srccall = ? """, params_ariadne)

    refused_orders = cursor_ariadne.fetchall()

    # Blocking orders
    rc = cursor_ariadne.execute(
        "UPDATE messages SET status = 'REFUSED' WHERE origin = 'IM' and status = 'RECEIVED' and srccall = ? ",
        params_ariadne)
    connection_ariadne.commit()

    logging.warning(
        "Too much pending messages for " +
        qra_to_be_blocked +
        " : they have been dropped.")

    # New email message is sent for making sender aware that its message has
    # been drpped

    for j in refused_orders:

        # Building email message :

        email_addr = j[3]
        m = "Subject: Js8call message refused. \n\n"
        m = m + "Your message of UTC " + \
            strftime(
                '%Y-%m-%d %H:%M:%S',
                time.gmtime(
                    j[1])) + " to " + j[2] + " was dropped." + "\n\n"
        m = m + "<< " + j[4] + " >>\n\n"
        m = m + "It has been refused because your station has too many messages in queue (max " + \
            str(max_message_number) + \
            ").\nPlease, try again later.\n\nThis message was generated by the mail2js8call gateway. Please, do not answer."
        m = m + "\n\n73 DE,\n" + gateway_callsign

        # Send "message expiration" email... sorry.

        rc = send_simple_email(
            smtp_server,
            smtp_username,
            smtp_password,
            gateway_email_address,
            email_addr,
            m)

        if rc != 0:

            logging.error(
                'SMTP server connection lost : dropped message was not sent.')


##########################################################################

# The new email message, valid, is inserted in the js8call inbox/outbox
# folder

############

#  js8call inbox/outbox database opening... the path is in .ini file
#  different from Linux and Windows.

js8call_db = sqlite3.connect(js8_call_db_path)
cursor_js8call = js8call_db.cursor()

rows_js8call = cursor_js8call.execute("SELECT * FROM inbox_v1")

for row in rows_js8call:

    id = (row[0])
    blob = (row[1])
    data = json.loads(blob)
#   print (data)

    fr = (f'{data["params"]["FROM"]}')
#    print(fr, end=" ")
    to = (f'{data["params"]["TO"]}')
#    print(to, end=" ")
    utc = (f'{data["params"]["UTC"]}')
#    print(utc, end=" ")
    id_internal = (f'{data["params"]["_ID"]}')
#    print(id_internal, end=" ")
    text = (f'{data["params"]["TEXT"]}')
#    print(text)

##########################################################################


####

rc = cursor_ariadne.execute(
    "SELECT * FROM messages WHERE origin = 'IM' and status = 'RECEIVED' ")
new = cursor_ariadne.fetchall()


##########################################################################
##
# Main new messagge update process....
##

for i in new:

    # ... read from Ariadne database the message to be passed to js8call..

    message_id = i[0]
    time_st = i[1]
    time_int = int(time_st)
    srccall = i[2]
    dst = i[4]
    message = i[5]

# ... change the json fields for the blog database field, starting from json model

    new_blob = json.loads(modello_json)
    f = new_blob["params"]["FROM"] = srccall
    f = new_blob["params"]["TO"] = dst
    f = new_blob["params"]["UTC"] = strftime(
        '%Y-%m-%d %H:%M:%S', time.gmtime(time_int))

# Js8call uses, as _ID field in Blog, a progressive nummber in microseconds from date
# GMT: Wednesday 5 July 2017 23:59:59.999 = 1499299199999 Linux Epoch UTC

    f = new_blob["params"]["_ID"] = int(epoch_timestamp) * 1000 - 1499299199999
    f = new_blob["params"]["TEXT"] = message
    f = new_blob["params"]["PATH"] = gateway_callsign
    f = new_blob["params"]["DIAL"] = 0
#  Useless effort : frequency is always 0 in the blob !!
#    f = new_blob["params"]["FREQ"] = frequency

    new_blob = json.dumps(new_blob)
#     print(new_blob)
#     print()
    # inbox_v1 key is tuple ... ?!
    params_js8call = (new_blob,)

# ... finally add the message to js8call database..

    rc = cursor_js8call.execute(
        "INSERT INTO inbox_v1 (blob) VALUES (?)", params_js8call)
    js8call_db.commit()

# .. important : ask sqlite for having the key of the newly inserted record..
    last_js8call_key = cursor_js8call.lastrowid

# .. and save the key on the Ariadne database, for keeping the link.
#     print(message_id)
    inbox_key = last_js8call_key
    status = 'TRIGGERED'
#     print(inbox_key)
    params_ariadne = (inbox_key, status, message_id)
    rc = cursor_ariadne.execute(
        "UPDATE messages SET inboxKey = ?, status = ? WHERE messageId = ?",
        params_ariadne)
    connection_ariadne.commit()

####

# In theory, duplication is infrequently still possible if two identical mail are sent.
# Not so common like in APRS...
# A whole check including "triggered" messages is in any case required,
# for cleaning inbox

# This is the list of all newly arrived messages in the period, including
# duplicated ones.

del new

rc = cursor_ariadne.execute(

    """SELECT messageId, time, inboxKey, srccall, emailAddr, dst, message, origin, status
      FROM messages WHERE origin = 'IM' and status = 'TRIGGERED' ORDER BY time ASC """)

new = cursor_ariadne.fetchall()

##

rc = cursor_ariadne.execute("""SELECT MIN(messages.messageId) AS minId, MIN(messages.time) AS minTime, MIN(messages.inboxKey) AS minInboxKey,
           messages.srccall, messages.emailAddr, messages.dst, messages.message,
           messages.origin, messages.status
           FROM messages GROUP BY messages.emailAddr, messages.dst, messages.message, messages.origin, messages.status
           HAVING messages.origin = 'IM' and messages.status = 'TRIGGERED'   """)
new2 = cursor_ariadne.fetchall()

# Studiare BENE !!

# From two dimensional lists, we extract the column 0 (messageId)

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
        logging.warning('email inbox duplication found : ' + str(inbox_key))


#  Physical deletion of duplicated messages from js8call inbox table...

        params_js8call = (inbox_key,)  # tuple ?
        rc = cursor_js8call.execute(
            "DELETE FROM inbox_v1 WHERE id = ?",
            params_js8call)
        js8call_db.commit()

#  Logical deletion of duplicated messages from Ariadne messages table...

        params_ariadne = ('DUPLICATED', i)
        rc = cursor_ariadne.execute(
            "UPDATE messages SET status = ? WHERE messageId = ?",
            params_ariadne)

connection_ariadne.commit()
logging.warning('Main process ended.')

##########################################################################

# First service cycle : all messages, having email origin, still not sent
# after the expiration limit, are deleted from inbox and marked as
# deleted in the Ariadne db

####

logging.warning('Expiration check process started.')

# expiring limit calculation for the not yet transmitted messages
expiring_limit = epoch_timestamp - int(message_expiration_days) * 86400

# for test
# expiring_limit = epoch_timestamp -int(1) * 86400

params_ariadne = (expiring_limit,)

# read expired messages from the main db..

rc = cursor_ariadne.execute(
    "SELECT * FROM messages WHERE time < ? and origin == 'IM' and status = 'TRIGGERED'  ",
    params_ariadne)
expired = cursor_ariadne.fetchall()

for i in expired:

    # fetch message to be deleted fields...

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

# Physical deletion of expired messages from js8call inbox table...

    rc = cursor_js8call.execute(
        "DELETE FROM inbox_v1 WHERE id=?", params_js8call)
    js8call_db.commit()

# Logical deletion of expired messages on Ariadne table...

    params_ariadne = ('EXPIRED', inbox_key)
    rc = cursor_ariadne.execute(
        "UPDATE messages SET status = ? WHERE inboxKey = ?",
        params_ariadne)
    connection_ariadne.commit()

# Build an automatic email message for making sender aware of expiration.
# Build email text, first item is Subject

    m = "Subject: js8call message expiration. \n\n"
    m = m + "Your message js8call of UTC " + \
        strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time_int)) + " :\n\n"
    m = m + "<< " + message + " >>\n\n"

    m = m + "This message was generated by the mail2js8call gateway.\nYour message could not be delivered, to its final, destination on time.\n\n"
    m = m + "73, DE\n" + gateway_callsign

# Send expiration email

    rc = send_simple_email(
        smtp_server,
        smtp_username,
        smtp_password,
        gateway_email_address,
        email_addr,
        m)

    logging.warning('Sending EXPIRATION email for message : ' + str(inbox_key))

    if rc != 0:

        logging.error(
            'SMTP server connection lost : exp message was not sent.')

logging.warning('Expiration check process ended.')

##########################################################################

# Second service cycle : all messages no more in the js8call inbox,
# were dropped by the sysop and a feebcak email message is sent back to
# the sender

####

logging.warning('SYSOP dropping check process started.')


# ... read from the database the messages that can be potentially sent.
# .. left join better...

rc = cursor_ariadne.execute(
    "SELECT * FROM messages WHERE origin == 'IM' and status = 'TRIGGERED' ")
triggered = cursor_ariadne.fetchall()


for i in triggered:

   # fetch message fields

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
#     print(inbox_key)

#  ... without outer join, check if the message is still in the inbox/outbox table...

#  ... if not, it's was deleted manually by the user

    params_js8call = (inbox_key,)  # tuple ?
    rc = cursor_js8call.execute(
        "SELECT id FROM inbox_v1 WHERE id = ?",
        params_js8call)
    missing = cursor_js8call.fetchone()

    if missing is None:

        # Logical deletion of sent email originated messages on Ariadne
        # table...

        params_ariadne = ('DROPPED', inbox_key)
        rc = cursor_ariadne.execute(
            "UPDATE messages SET status = ? WHERE inboxKey = ? ",
            params_ariadne)
        connection_ariadne.commit()

# We generate an warning email to the sender if the message is set
# to DROPPED status..

# Build email text, first item is Subject

        m = "Subject: Your message has been dropped by the sysop.\n\n"

        m = m + "Your message js8call of UTC " + \
            strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time_int)) + " :\n\n"
        m = m + "<< " + message + " >>\n\n"

        m = m + "This message has been deleted by the js8call gateway sysop.\n"
        m = m + "This message was generated by the mail2js8call gateway, please do not answer."
        m = m + "\n\n73\n" + gateway_callsign

# ...sending email via SMTP...

        rc = send_simple_email(
            smtp_server,
            smtp_username,
            smtp_password,
            gateway_email_address,
            email_addr,
            m)

        logging.warning(
            'Sending DROPPED email for message : ' +
            str(inbox_key))

        if rc != 0:

            logging.error(
                'SMTP server connection lost : drop message was not sent.')

logging.warning('SYSOP dropping check process ended.')


##########################################################################

# Third service cycle : all messages having status SENT in JS8CALL inbox table
# have been successfully delivered

####

logging.warning('Sent message check process started.')

rc = cursor_ariadne.execute(
    "SELECT * FROM messages WHERE origin = 'IM' and status = 'TRIGGERED' ")
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

# We generate an warning email to the sender if the message is set
# to SENT status..

# Build email text, first item is Subject

            m = "Subject: Your message has been sent to its final destination.\n\n"

            m = m + "Your message js8call of UTC " + \
                strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time_int)) + " :\n\n"
            m = m + "<< " + message + " >>\n\n"

            m = m + "This message has been sent by the js8call gateway.\n"
            m = m + "This message was generated by the mail2js8call gateway, please do not answer."
            m = m + "\n\n73\n" + gateway_callsign

# ...sending email via SMTP...

            rc = send_simple_email(
                smtp_server,
                smtp_username,
                smtp_password,
                gateway_email_address,
                email_addr,
                m)

            logging.warning(
                'Sending ACK email for message : ' +
                str(inbox_key))

            if rc != 0:

                logging.error(

                    'SMTP server connection lost : ack message was not sent.')

logging.warning('Sent message check process ended.\n')


# Closing db connections
cursor_ariadne.close()
cursor_js8call.close()

# Closing imap connection
imap.close()
imap.logout()

sys.exit()
