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
#  Technical contact paintomicsai@gmail.com
#**************************************************************

from src.common.Util import Model

class Report (Model):
    """A user-submitted report (error notification, organism request or other).

    Reports are persisted before any delivery attempt, so an outage at the mail
    provider can never lose one. Fields are plain scalars on purpose: adaptBSON
    turns None into the string "None", so absent values are stored as "".
    """
    #******************************************************************************************************************
    # CONSTRUCTORS
    #******************************************************************************************************************
    def __init__(self, report_type=""):
        self.report_id = ""
        self.report_type = report_type or "other"
        self.user_email = ""
        self.user_name = ""
        self.message = ""
        self.submitted_at = ""
        self.delivered = False
        self.delivery_error = ""

    #******************************************************************************************************************
    # GETTERS AND SETTER
    #******************************************************************************************************************
    def getReportID(self):
        return self.report_id

    def setReportID(self, report_id):
        self.report_id = str(report_id or "")

    def getReportType(self):
        return self.report_type

    def setReportType(self, report_type):
        self.report_type = report_type

    def getUserEmail(self):
        return self.user_email

    def setUserEmail(self, user_email):
        self.user_email = user_email or ""

    def getUserName(self):
        return self.user_name

    def setUserName(self, user_name):
        self.user_name = user_name or ""

    def getMessage(self):
        return self.message

    def setMessage(self, message):
        self.message = message or ""

    def getSubmittedAt(self):
        return self.submitted_at

    def setSubmittedAt(self, submitted_at):
        self.submitted_at = submitted_at or ""

    def isDelivered(self):
        return self.delivered

    def setDelivered(self, delivered):
        self.delivered = bool(delivered)

    def getDeliveryError(self):
        return self.delivery_error

    def setDeliveryError(self, delivery_error):
        self.delivery_error = delivery_error or ""
