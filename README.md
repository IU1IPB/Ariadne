**ARIADNE : APRS and INTERNET gateway to JS8CALL network.**

ARIADNE is born following the need of connecting a low cost Patagonian alpinist expedition without using expensive Thuraya satellites phones.

Ariadne is a small group of apps, useful for connecting APRS – over – internet HAM network or internet emails to JS8call network, allowing the transfer of short APRS or “SMS like” messages to the JS8CALL network as “sleeping” messages, ready to be retrieved by remote radio stations that sends standard “QUERY MSGS“ command to the @ALLCALL group.

Answers sent back throw js8call gateway by remote stations can also be piped back till the sender QRA using the desired APRS or email channel, without the need of addressing answers to existent well working APRS or EMAIL-2 gateways.

The gateway can answer to @ALLCALL QUERY MSGS , telling if the desired station can be connected via aprs or email.

Some checks are made to avoid gateway cluttering, by checking message length, number of queued messages, traffic, not sent messages expiration, message duplication (mainly from APRS), blacklist or QRA correctness and so on.

A text message censorship was also provided, but at the moment ChatGPT program access is no more free neither for small not-professional users and the feature has been deactivated.

Feedback is sent back to the sender by APRS / email when the message was delivered or dropped.

A few inquiries are available: email senders can ask the gateway for having the full list of “heard” stations, while APRS users can check JS8CALL ANSRVR group (in MQTT like “broker /subscriber / publisher” logic) to get the list of active gateways worldwide (with locator and email address) or directly for asking which station can connect a desired js8call QRA.

The tool has been well tested on unit tests cases, but it lack an extensive field use. It must be considered in beta status. **Do not trust it for emergency communications**.

Please consider **local radio regulations**, mainly regarding the transmission of QTC messages on behalf of other stations, before activating Ariadne.

Future interface with radioAPRS (using Direwolf) and MQTT public brokers will be perhaps available in the future.

**TECHNICALITIES**

ARIADNE uses five python3 programs, without any Graphical interface.

It interacts with JS8CALL fantastic program only reading or writing its inbox/outbox standard database : the real time API provided by JS8CALL are not used.

It has been well tested on Linux / Debian, but it runs also under Windows.

The gateway JS8CALL radio station **must** have HeartBeat networking and automatic answers switched on without any timeout, working in full automatic status.

The main programs should be scheduled periodically in sequence (they are usually fast), with an execution frequency coherent with the automatic HeartBeat generation timing : usual setup expects a full execution each 10-15 minutes.

The realTimeAprsGet.py program it’s a never-ending daemon that check continuously the APRS network in order to answer to requests to ANSRVR group : it’s execution it’s not mandatory (loosing the ANSRVR capability), but it must be scheduled at system startup or defined as SYSTEMCTL service (or equivalent n Windows).

It’s also possible to activate only the APRS side or only the email side of the gateway, loosing some capabilities, only scheduling the desired programs (see below).

For activating APRS full e-gateway the following programs are required :

-   **realTimeAprsGet** : daemon that check aprs.is in real time and answers to ANSRVR group requests
   
1.  **historicalQsoStatistics** ; it periodically update the “heard” (by the gateway js8call) list of stations, reading JS8CALL data.
2.  **aprs2js8call** : main program : it checks if on aprs there are messages directed to any radio callsign that can be bidirectionally received and, if found, it moves those messages in the js8call inbox/oubox for later delivery, after a QUERY MSGS command.
3.  **answerFromjs8call** : if a message is sent by remote radio station to/via gateway to an aprs (or email) “connectable” station, it forwards the message back (syntax js8call MESSAGE TO:[CALLSIGN] [MESSAGE] sent to gateway station) immediately via aprs or email.

For activating EMAIL gateway the following programs are required :

1.  **historicalQsoStatistics**
2.  **mail2js8call** : main program. It forwards short email messages sent to the gateway email address to the JS8CALL inbox/outbox for later delivery after a QUERY MSGS command. The email text is ignored. The email Subject MUST be built using the following template : JS8CALL FROM:\<SENDER CALLSIGN\> TO:\<DESTINATION CALLSIGN\> MSG: \<MESSAGE TEXT UP TO 160 ASCII digits\>
3.  **answerFromjs8call**

**SPECIFIC COMMANDS**

**EMAIL side :**

Email text is ignored. Only email Subject is checked.

1.  Sending message to JS8CALL gateway for further forward :

JS8CALL FROM:\<SENDER CALLSIGN\> TO:\<DESTINATION CALLSIGN\> MSG: \<MESSAGE TEXT \>

1.  Asking gateway for the list of stations that can be contacted:

JS8CALL HEARING?

**APRS side :**

1.  Normal APRS messages are forwarded without any special need to JS8CALL “HEARD” station
2.  Asking the ANSRVR for knowing if there are active JS8CALL gateways :

\<ASKING CALLSIGN \> ANSRVR: CQ JS8CALL GATEWAY?

Each active gateway that receive this request, will answer automatically via ANSRVR with the following APRS message :

JS8CALL GATEWAY: \<gateway locator\> \<gateway email address\>

1.  Asking the ANSRVR for knowing if a station can be reached :

CQ JS8CALL HEARING? \< requested callsign\>

Each active gateway that receive this request, will answer automatically with the following APRS message :

\<requested callsign\> HEARD BY \<gateway callsign\> \<frequency\> \<snr\> \<last contact date and UTC time\>

Or…

QRA \< requested callsign\> IS NOT HEARD BY \<gateway callsign\>

**INSTALL**

A python3 standard installation is required to execute Ariadne.

1.  GIT CLONE the folder and put it wherever you like (e.g. in user space for avoiding administrative authorizations)
2.  Create virtual Python environment, as mandatory on the new Pythons installations :

source ariadne.venv/bin/activate

1.  Install dependencies:

    pip3 install requests

    pip3 install aprslib

1.  Edit the config.ini file according to your needs. The file should be self-explanatory, but in any case you have to insert at least : the js8call installation folder (that changes between Windows or Linux systems), js8call gateway callsign, its Maidenhead locator in form AAbbcc or AAbb, the APRS-FI self-generating password for your station (if you plan to use APRS), the self-generating APRS-IS passkey (if you plan to use ANSRVR automatic answering), the gateway email address account data (e.g. gmail username, server address, app-key) both for reading email and for sending them and finally some station behaviour settings (e.g. the number of hours since the last bidrectional QSO for which an “heard” station can be considered reachable).
2.  You can now schedule the programs in sequence; a possible template is :

0,10,20,30,40,50 **historicalQsoStatistics**

2,12,22,32,42,52 **aprs2js8call**

5,15,25,35,45,55 **mail2js8call**

8,18,28,38,48,58 **answerFromjs8call**

At startup or as service : **realTimeAprsGet**

1.  That’s all. Please consider that the programs write a log file in the same folder (ariadne.log), that records all events but that grows quickly : please consider to periodically archive manually or via logrotate; an utility program (archivingGatewayHistory.py) can be periodically used in order to reduce js8call database size and to archive js8call contact logs.
