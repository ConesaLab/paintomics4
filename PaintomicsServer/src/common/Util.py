#***************************************************************
#  This file is part of Paintomics v3
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  Paintomics is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Paintomics.  If not, see <http://www.gnu.org/licenses/>.
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomics4@outlook.com
#**************************************************************
from PIL.Image import open as image_open

class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

class Model (object):
    def parseBSON(self, bsonData):
        bsonData.pop("_id")
        for (attr, value) in bsonData.items():
            setattr(self, attr, value)

    def toBSON(self):
        return  self.__dict__

    def clone(self):
        import copy
        newobj = copy.deepcopy(self) # deep (recursive) copy
        return newobj


def chunks(l, n):
    """
        This function divides an array in n parts

        @param {Array} l, the array object
        @param {Int} n, number of parts
        @returns list of n arrays
    """
    return [l[i:i+n] for i in range(0, len(l), n)]


def getImageSize(imagePath):
    image = image_open(imagePath)
    return image.size

def unifyAndSort(seq, criteria=None):
    seq = sorted(seq, key=criteria)
    # order preserving
    if criteria is None:
       def idfun(x): return x
    seen = {}
    result = []
    for item in seq:
       marker = criteria(item)
       # in old Python versions:
       # if seen.has_key(marker)
       # but in new ones:
       if marker in seen: continue
       seen[marker] = 1
       result.append(item)
    return result


def sendEmail(ROOT_DIRECTORY, toEmail, toName, subject, _message, fromEmail=None, fromName=None, isHTML=False):
    """
    Send email using SMTP via SendGrid.

    Args:
        ROOT_DIRECTORY: Base directory path (kept for compatibility, not used)
        toEmail: Recipient email address
        toName: Recipient name
        subject: Email subject
        _message: Email body content (HTML or plain text)
        fromEmail: Sender email (defaults to config value)
        fromName: Sender display name (defaults to config value)
        isHTML: Whether the message is HTML formatted (default: False)

    Raises:
        Exception: If SMTP credentials are not configured or email sending fails
    """
    import smtplib
    import logging
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.utils import formataddr
    from src.conf.serverconf import (
        EMAIL_FROM_ADDRESS, EMAIL_FROM_DISPLAY,
        SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_USE_TLS
    )

    # Use default sender if not provided
    if fromEmail is None:
        fromEmail = EMAIL_FROM_ADDRESS
    if fromName is None:
        fromName = EMAIL_FROM_DISPLAY

    # Validate SMTP credentials are configured
    if not SMTP_PASSWORD:
        error_msg = "SMTP_PASSWORD is not configured. Please set the environment variable."
        logging.error(error_msg)
        raise Exception(error_msg)

    # Create message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = formataddr((fromName, fromEmail))
    msg['To'] = formataddr((toName, toEmail))

    # Attach the message body
    mime_type = 'html' if isHTML else 'plain'
    msg.attach(MIMEText(_message, mime_type, 'utf-8'))

    # Send email via SMTP
    try:
        # Connect to SMTP server
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        server.ehlo()

        # Use TLS if configured
        if SMTP_USE_TLS:
            server.starttls()
            server.ehlo()

        # Authenticate
        server.login(SMTP_USERNAME, SMTP_PASSWORD)

        # Send email
        server.sendmail(fromEmail, toEmail, msg.as_string())

        # Close connection
        server.quit()

        logging.info(f"Email sent successfully to {toEmail} (Subject: {subject})")
        return

    except smtplib.SMTPException as e:
        error_msg = f"SMTP error sending email: {str(e)}"
        logging.error(error_msg)
        raise Exception(error_msg)
    except Exception as e:
        error_msg = f"Failed to send email via SMTP: {str(e)}"
        logging.error(error_msg)
        raise Exception(error_msg)


def adapt_string(the_string):
    try:
        return str(the_string)
    except:
        try:
            import unicodedata
            return str(''.join(c for c in unicodedata.normalize('NFD', the_string) if unicodedata.category(c) != 'Mn'))
        except Exception:
            try:
                import re
                return str(re.sub('[^A-Za-z0-9]+', '', the_string))
            except:
                return "INVALID STRING"