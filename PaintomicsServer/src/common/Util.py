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
#  Technical contact paintomics4@gmail.com
#**************************************************************
from PIL.Image import open as image_open
from chardet import detect # get the encoding of a file

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


def resolveWithin(baseDir, fileName):
    """Resolve `fileName` inside `baseDir`, or None if it escapes.

    Routes that act on a file named by the request used to concatenate:

        os.remove(DESTINATION_DIR + fileName)
        open("{path}/{file}".format(path=userDir, file=fileName))

    A `..` in the name walks out of the directory, which made those an
    arbitrary file delete and an arbitrary file read respectively. Flask's
    `send_from_directory` refuses that on its own, so the download handler was
    safe on the branch that served an attachment and unsafe on the branch that
    streamed the file itself.

    `realpath` is what does the work: it collapses `..` and *also* resolves
    symlinks, so a link planted inside the directory cannot be used to step
    outside it. Containment is then checked with `commonpath` rather than
    `startswith`, because a plain prefix test accepts a sibling directory whose
    name merely begins the same way (`inputData` vs `inputData_evil`).

    Returns the absolute resolved path when it is genuinely under `baseDir`,
    otherwise None. Existence is not required -- the caller decides that -- but
    the base directory itself is refused, since it is not a file to act on.
    """
    import os

    if not fileName or not str(fileName).strip():
        return None

    fileName = str(fileName)
    # A NUL cannot appear in a real name and breaks C-level path handling.
    if "\x00" in fileName:
        return None

    base = os.path.realpath(baseDir)
    # os.path.join drops the base entirely if fileName is absolute, so an
    # absolute path would otherwise be honoured verbatim.
    candidate = os.path.realpath(os.path.join(base, fileName))

    if candidate == base:
        return None

    try:
        if os.path.commonpath([base, candidate]) != base:
            return None
    except ValueError:
        # Different drives on Windows; not the same tree by definition.
        return None

    return candidate


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


# Encoding is decided from a bounded prefix. Omics uploads routinely reach
# hundreds of megabytes, and running chardet over the whole buffer costs time
# and memory to answer a question the first chunk already settles.
_ENCODING_SNIFF_BYTES = 256 * 1024


def _decodes_as_utf8(sample, isPartial):
    """Whether `sample` is valid UTF-8.

    When the sample is only a prefix of a larger file, a multi-byte character
    can be cut in half at the boundary. That is not evidence of a different
    encoding, so a failure inside the last three bytes is forgiven.
    """
    try:
        sample.decode('utf-8-sig')
        return True
    except UnicodeDecodeError as exc:
        return isPartial and exc.start >= len(sample) - 3


def ensure_utf8(filepath):
    """Rewrite `filepath` as UTF-8 in place when it is in some other encoding.

    Returns None on success, or a human-readable reason when the encoding could
    not be resolved. Callers turn that reason into a validation message: an
    unreadable upload is bad input, and it used to escape as a bare
    UnicodeDecodeError.

    UTF-8 is tested directly before chardet is consulted. Guessing first is
    unsafe: single-byte codecs such as cp1252 accept *any* byte sequence, so a
    misdetected UTF-8 file would be silently rewritten into mojibake rather
    than left alone.
    """
    with open(filepath, 'rb') as handle:
        sample = handle.read(_ENCODING_SNIFF_BYTES + 1)

    # An empty file has no encoding to fix; emptiness is reported elsewhere.
    if not sample:
        return None

    isPartial = len(sample) > _ENCODING_SNIFF_BYTES
    if _decodes_as_utf8(sample, isPartial):
        return None

    detected = detect(sample).get('encoding')
    if not detected:
        return "the character encoding could not be determined, please save the file as UTF-8"

    try:
        with open(filepath, 'rb') as handle:
            text = handle.read().decode(detected)
    except (UnicodeDecodeError, LookupError):
        return ("the file could not be read as " + str(detected) +
                ", please save it as UTF-8")

    # newline='' keeps the line endings exactly as decoded; the readers below
    # already cope with CRLF, and rewriting them here would be a silent edit of
    # the user's file.
    with open(filepath, 'w', encoding='utf-8', newline='') as handle:
        handle.write(text)
    return None
