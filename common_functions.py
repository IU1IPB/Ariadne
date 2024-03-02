#!/home/pi/Ariadne/ariadne.venv/bin/python3

# !/usr/bin/env python3

"""

This is the common function library of the Ariadne Project
Each function is self-explanatory.

"""

import configparser  # .ini file manager
import re  # regular expression library
import smtplib  # SMTP
import socket   # socket library
import sqlite3
import ssl
#import requests  # CURL like library
import aprslib  # APRS library

from urllib.parse import quote  # Libreria urlencode semplificata
from pathlib import Path  # Gestione path dei file

#

__author__ = "Ugo PODDINE, IU1IPB"
__copyright__ = "Copyright 2024"
__credits__ = ["Ugo PODDINE"]
__license__ = "GPL"
__version__ = "1.0.1"
__maintainer__ = "Ugo PODDINE"
__email__ = "iu1ipb@yahoo.com"
__status__ = "Production"


# Configuration

config = configparser.ConfigParser()  # .ini file manager

# Get Aprs.is Key (20)
config.read('config.ini')
api_key_aprs_is = (config['DEFAULT']['api_Key_AprsIs'])

# à


def check_qra(QRA):
    """
    Check QRA according to :

    a) https://ham.stackexchange.com/questions/1352/how-can-i-tell-if-a-call-sign-is-valid
      Some LOTW QRA are in any case wrongly considered invalid
    b) APRS validation rule (Python 3.11)

    """

# From Python 3.11 : APRS.IS rule. Better check, e.g, IA5/IZ1BPS ok
#    pattern = re.compile("(?>[1-9][A-Z][A-Z]?+[0-9]|[A-Z][2-9A-Z]?[0-9])[A-Z]{1,4}+")

# Python : current version
    pattern = re.compile("\\d?[a-zA-Z]{1,2}\\d{1,4}[a-zA-Z]{1,4}")

    # Check QRA according to aprs.fi rule (QRA maiuscolo)
#    pattern = re.compile("(?>[1-9][A-Z][A-Z]?+[0-9]|[A-Z][2-9A-Z]?[0-9])[A-Z]{1,4}+")

    if pattern.match(QRA) is None:

        return False

    return True

############################


def send_simple_email(smtp_server, smtp_username, smtp_password,
                      sender_email_addr, receiver_email_addr, message_as_string):
    """
    Send SMTP simple text email
    Mime text must come here after as_string() method call

    """
    SMTP_PORT = 465  # For smtp port for SSL

    rc = test_alive_ip_port(smtp_server, SMTP_PORT)

    if rc != 0:

        return rc  # Errore connessione al server livello rete

    context = ssl.create_default_context()

    with smtplib.SMTP_SSL(smtp_server, SMTP_PORT, context=context) as smtpServer:

        try:

            smtpServer.login(smtp_username, smtp_password)
            smtpServer.ehlo()  # added on 30/1/24
            smtpServer.sendmail(
                sender_email_addr,
                receiver_email_addr,
                message_as_string)
            smtpServer.quit()
            return 0

        except smtplib.SMTPException as e:  # Errore connessione livello SMTP

            #  error_code = e.smtp_code
            #  error_message = e.smtp_error

            return e

############################


def test_alive_ip_port(ip_address, port):
    """
    Check if IP address is reacheable and port is open

    """

    return 0  # DEBUG

    try:

        a_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        a_socket.settimeout(2)   # 2 seconds timeout
        location = (ip_address, port)
        check = a_socket.connect_ex(location)

        if check == 0:

            return check

    except socket.error as e:

        return e

############################


#def send_msg_to_aprs_findu(sender_callsign, destination_callsign,
#                           plain_text_message):
#    """
#
#    Send the aprs message via findu.com
#
#    """

#    resp = test_alive_ip_port("findu.com", 80)
#    if resp != 0:

#        return resp

#    connection_string = "http://www.findu.com/cgi-bin/sendmsg.cgi?fromcall=" + \
#        sender_callsign + "&tocall=" + destination_callsign + "&msg="

#    msg = quote(plain_text_message)  # Plain test urlencode
#    resp = requests.get(connection_string + msg)
#    print(connection_string + msg)
#    if resp.ok:
#
#        return 0

#    return resp



############################

def send_msg_to_aprs(sender_callsign, destination_callsign,
                     plain_text_message):
    """
    Send aprs message via APRS.IS

    """


# Build message with the following structure :
# 'IU1IPB>APRS,TCPIP*,qAC,T2ROMANIA::TU5IV    :JS8CALL GATEWAY: JN34qx iu1ipb(at)yahoo.com'

    t = destination_callsign + "          "
    destination_callsign = t[:9]

    aprs_message = sender_callsign + '>APRS,TCPIP*,qAC,T2ROMANIA::' + \
        destination_callsign + ':' + plain_text_message.upper()

# a valid aprs.is passcode for the callsign is required in order to send

    try:

        AIS = aprslib.IS(sender_callsign, passwd=api_key_aprs_is, port=14580)
        AIS.connect()
        AIS.sendall(aprs_message)

    except (aprslib.ParseError, aprslib.UnknownFormat, aprslib.exceptions.LoginError) as exp:

        return exp

    return 0

#############################


def is_database_locked(db):
    """
    Verify is the sqlite database is locked

    """

    try:
        with db:
            db.execute("BEGIN EXCLUSIVE")

            # If it reaches here, the lock was acquired successfully

            db.execute("COMMIT")

            return False  # Database is not locked

    except sqlite3.OperationalError:

        return True  # Failed to acquire the lock: database is locked

# Esempio di utilizzo:
# db = sqlite3.connect("nome_del_database.db")
# locked = is_database_locked(db)
# print(locked)


#############################

def get_configuration():

    """
    Return configuration parameters from config.ini
    in the application folder

    """

    config.read('config.ini')


# return js8call path (0,1)
    js8call_folder = (config['DEFAULT']['js8call_Folder'])
    js8call_folder = js8call_folder.replace("${home_dir}", str(Path.home()))
    js8call_folder = Path(js8call_folder)
    js8_call_db_path = js8call_folder / "inbox.db3"

# Get Aprs.fi Key (2)
    api_key_aprs_fi = (config['DEFAULT']['api_Key_AprsFi'])

# Get Aprs.is Key (20)
    api_key_aprs_is = (config['DEFAULT']['api_Key_AprsIs'])

# Get JS8call station callsign QRA (APRS to JS8CALL gateway) (3)
    gateway_call_sign = (config['DEFAULT']['gateway_Call_Sign'])

# Return number of days before message expiration (4)
    message_expiration_days = (config['DEFAULT']['message_Expiration_Days'])

    if int(message_expiration_days) < 2:

        message_expiration_days = 2

# Return number of hours for which a remote js8call station can be
# considered alive (5)
    station_alive_limit_hours = (
        config['DEFAULT']['station_Alive_Limit_Hours'])
    station_alive_limit_hours = int(station_alive_limit_hours)

    if station_alive_limit_hours < 2:

        station_alive_limit_hours = 24

# Active radio stations are considered "alive" their last snr was greater than... db
# Too weak stations are not reliable. (19)
    station_alive_snr = config['DEFAULT']['station_Alive_snr']
    station_alive_snr = int(station_alive_snr)

# Return banned APRS callsign : APRS blacklist (6)
    banned_qra_aprs = (config['DEFAULT']['banned_Qra_APRS'])

# Return whitelistd APRS QRA : APRS call accepted in exception (7)
    white_Listed = (config['DEFAULT']['white_Listed'])

# Return banned js8Calll / HF QRA (8)
    banned_Qra_Js8call = (config['DEFAULT']['banned_Qra_Js8call'])

# IMAP inbound email account connection parameters (9,10,11)
    imap_username = (config['DEFAULT']['imap_Username'])
    imap_password = (config['DEFAULT']['imap_Password'])
    imap_server = (config['DEFAULT']['imap_Server'])

# SMTP outbound email account connection parameters (12,13,14)
    smtp_username = (config['DEFAULT']['smtp_Username'])
    smtp_password = (config['DEFAULT']['smtp_Password'])
    smtp_server = (config['DEFAULT']['smtp_Server'])

# Gateway station email addresss (15)
    gateway_email_address = (config['DEFAULT']['gateway_Email_Address'])

# Gateway station locator (16)
    gateway_locator = (config['DEFAULT']['gateway_locator'])

# Gateway APRS ANSRVR group name for publishing
# Subscription in MQTT logic (21)
    gateway_announcement_ANSRVR_group = (
        config['DEFAULT']['gateway_announcement_ANSRVR_group'])
    gateway_announcement_ANSRVR_group = gateway_announcement_ANSRVR_group.strip()

# Maximum number of pending messages allowed for each callsign (17)
    max_message_number = (config['DEFAULT']['max_message_number'])
    max_message_number = int(max_message_number)

# When message from email is received, check if the
# destination station is in "heard" list (18)
    email_check_dst_heard = config.getboolean(
        'DEFAULT', 'email_check_dst_heard')

    return js8call_folder, js8_call_db_path, api_key_aprs_fi, \
        gateway_call_sign, message_expiration_days, \
        station_alive_limit_hours, banned_qra_aprs, \
        white_Listed, banned_Qra_Js8call, imap_username, \
        imap_password, imap_server, smtp_username, \
        smtp_password, smtp_server, gateway_email_address, \
        gateway_locator, max_message_number, \
        email_check_dst_heard, station_alive_snr, \
        api_key_aprs_is, gateway_announcement_ANSRVR_group

########################################################

def calculate_checksum(string):

    """
    Return string checksum in three digit ASCI
    Credits to ChatGPT

    """

    crc = zlib.crc32(string.encode())

    # Prendiamo solo i 16 bit più significativi per ridurre la checksum a 3 caratteri ASCII

    crc &= 0xFFFF

    # Convertiamo la checksum in una stringa di 3 caratteri ASCII UTF-8

    checksum = hex(crc)[2:].upper().zfill(4)  # zfill aggiunge zeri a sinistra per garantire una lunghezza di 4 caratteri
    checksum = checksum[-3:]  # Prendiamo solo gli ultimi 3 caratteri

    return checksum

