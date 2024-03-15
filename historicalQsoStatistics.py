#!/home/pi/Ariadne/ariadne.venv/bin/python3

### #!/usr/bin/env python3


"""
This is the statisical part og Ariadne tool.
It periodically analyze the js8call standard txt log file,
extraction all stations that can have a bi-directional contact
with the gatewy station (the QRA marked by * in js8call), with
signal strainght and heartbeat time.
Data are stored in adatabase table.
Information are used to answer to "HEARING?" requests and to filter inbound
requests from aprs or email.
"""

import calendar  # timestamp UTC
import configparser  # .ini configuration files library
import datetime  # date & time..
import logging  # log manager
import os
import re  # Regular expression library
import sqlite3  # sqlite3 database library
import sys
import time # Time date library
import locale # Get "locales" user default, e.g. decimal separator

from datetime import datetime

# common functions

from common_functions import get_configuration  # lanscape parameters
from common_functions import check_qra
from common_functions import is_database_locked

####

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
#  .ini file read settings
##

# Get configuration parameters from config.ini
configuration = get_configuration()

# Path js8call
js8call_db_path = configuration[1]
js8call_folder = configuration[0]


# JS8call station QRA (APRS to JS8CALL gateway)
gateway_call_sign = configuration[3]

# Banned APRS callsign
banned_qra_aprs = configuration[6]
banned_qra_aprs = banned_qra_aprs.split(',')


# Banned js8call callsign
banned_qra_js8call = configuration[8]
banned_qra_js8call = banned_qra_js8call.split(',')


# Whitlisted APRS callsign
whitelisted_qra_aprs = configuration[7]
whitelisted_qra_aprs = whitelisted_qra_aprs.split(',')

# Get now() time in UTC and convert to Epoch
epoch_timestamp = calendar.timegm(time.gmtime())

# Get decimal separatore for the user : from dictionary
locale.setlocale(locale.LC_ALL, '')
t = locale.localeconv()
decimal_separator = t['mon_decimal_point']
#print ("Separator is = ", decimal_separator)


# Initializing log...
logging.warning('>>> Program : ' + os.path.basename(__file__) + ' started.')

##########################################################################

# The js8call logfile is imported in sqlite db table

####

##########################################################################

# Preliminary checks in db : are trhey locked ?

db = sqlite3.connect("ariadne.db3")
locked = is_database_locked(db)

if locked is True:

    logging.error('Ariadne database is locked : aborted.')
    sys.exit(4)  # nothing can be done

connection_ariadne = sqlite3.connect("ariadne.db3")

# connection_ariadne= sqlite3.connect("aprs.db3:memory:?cache=shared")
# In memory, to be checked

cursor_ariadne = connection_ariadne.cursor()

# Unable to create a primary key using several fields : in theory possible and possible from GUI.
# Added instead an unique index

cursor_ariadne.execute(
    "CREATE TABLE IF NOT EXISTS qso (time INTEGER NOT NULL, frequency REAL NOT NULL, overlay INTEGER NOT NULL, snr REAL, srccall TEXT NOT NULL, dst TEXT NOT NULL, message TEXT) ")

# ....unique index
cursor_ariadne.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS pk_qso ON qso (time,frequency,overlay,srccall,dst)")

date_format = '%Y-%m-%d %H:%M:%S'

#
# js8call log file import. Cleansing made : text fields are often filled with abnormal /n
#

# Importing js8call logfile...
js8call_log = js8call_folder / "DIRECTED.TXT"

if os.path.exists(js8call_log) is False :

      logging.error('JS8call log file DIRECTED.TXT is missing : aborted.')
      sys.exit(4)


#... "ignore" is required to skip not UTF8 charcters in the log files, quite dirty...
# context manager "with"..
with open(js8call_log, 'r', encoding='utf8', errors='ignore') as tsv:

    for line in tsv:

#        line = line.encode('utf-8').strip()
#        line = unicodedata.normalize('NFKD', line)
        line = re.sub(r'[^\x00-\x7F]+',' ', line) # strip not-ascii codes
        row = line.split()
        line = line.strip('\t')
#        print(line)
        t = (line[0:10])
        date = t.strip()
#        print(date, end=" ") 
        t = (line[10:19])
        time = t.strip()
#        print(time, end=" ")
        t = (line[20:28])
        frequency = t.strip()
#        print(frequency, end = " ")
        t = (line[28:33])
        overlay = t.strip()
#        print(overlay, end = " ")
        t = (line[33:37])
        snr = t.strip()
#        print(snr, end = " ")
        t = line.find(':', 37)
        src = line[37:t]        
        src = src.strip()
 #       print (src, end = " ")
        t1 = line[t+2:]
        t2 = t1.find(" ")
        dst = t1[0:t2]
        dst = dst.strip()
        text = t1[t2:]
        text = text.strip("\n")
        text = text.lstrip()

        del t, t1, t2
#        print (dst, text)
        qso_time = date + " " + time

#  ... and qsotime must be '%Y-%m-%d %H:%M:%S'
# ... very long message texts are saved in a new line without date : 
# in this case the message will be triuncated in Ariadne Db

        try:

            qso_time = datetime.strptime(qso_time, date_format)

        except ValueError:
#            raise ValueError("Incorrect data format, should be YYYY-MM-DD")

            continue


#        qso_time = datetime.strptime(qso_time, date_format)
        epoch = calendar.timegm(qso_time.timetuple())  # QSO date / time in linux epoch UTC

# We need to move to QSO database :
# a) Bidirectional QSOs, when receiver QRA = gateway station QRA (*), since others
# contact are not useful in gateway logic.
# b) The @ALLCALL requestes, but at the moment only the ones belonging to 'QUERY CALL" family , since we should answer


        if (dst == gateway_call_sign) or ( dst == "@ALLCALL" and text[1:11] == 'QUERY CALL') :


# Frequency, snr and overlay must be trasnformed in number from string,
# considering the local decimal separator 

            t = (re.findall("\\d+\\" + decimal_separator +"\\d+", frequency))  ## Decimal separtor from lacale
            frequency = t[0]
#            print(frequency,end=" ")

# snr is an integer signed number

            t = (re.findall("(-*[0-9]+)", overlay))
#            overlay = t[0]
 
            t = (re.findall("(-*[0-9]+)", snr))
#            snr = t[0]
#            print(overlay,end=" ")
#            print(snr, src, dst, " = ", text, text[1:10],"-")

# Check if the QRA has been blacklisted... from HF side

            if src in banned_qra_js8call:

                continue

            if check_qra(src) is False:    # check if the receiver call is a QRA

                continue

# New record have to be added to database

            params_aprs = (
                epoch, frequency, overlay, snr, src, dst, text)

            cursor_ariadne.execute(
                "INSERT OR IGNORE INTO qso VALUES (?, ?, ?, ?, ?, ?, ?)", params_aprs)

# Commit ...
            connection_ariadne.commit()

# Log closing
logging.warning('Main process ended.')

# Closing db connections
cursor_ariadne.close()
sys.exit()
