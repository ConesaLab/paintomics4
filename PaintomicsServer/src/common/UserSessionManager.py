#***************************************************************
#  This file is part of Paintomics v3
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  Paintomics is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Paintomics.  If not, see <http://www.gnu.org/licenses/>.
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomicsai@gmail.com
#**************************************************************
from src.common.ServerErrorManager import CredentialException
from src.conf.serverconf import ADMIN_ACCOUNTS
from src.common.DAO.UserDAO import UserDAO

class UserSessionManager(object):

    #Implementation of the singleton interface
    class __impl:
        logged_users=dict()

        def registerNewUser(self, user_id):
            import string
            import secrets
            user_id = str(user_id)
            # secrets, not random: this token is the entirety of what
            # isValidUser checks a request against, and `random` is the
            # Mersenne Twister -- reproducible by design and reconstructable
            # from a run of its own output. Length does not help; a long draw
            # from a predictable stream is as guessable as the stream. A site
            # that hands out guest sessions on request hands out samples of
            # that stream on request too.
            #
            # Same alphabet and same length as before, so nothing stored or
            # sent changes shape and no live session is invalidated.
            sessionToken =''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(50))
            self.logged_users[user_id] = sessionToken
            return sessionToken

        def removeUser(self, user_id, sessionToken):
            user_id = str(user_id)
            assignedSessionToken = self.logged_users.get(user_id, None)
            if (assignedSessionToken != None and assignedSessionToken == sessionToken):
                del self.logged_users[user_id]
                return True
            return False

        def isValidUser(self, user_id, sessionToken):
            user_id = str(user_id)
            # A missing userID with no session token is the anonymous "nologin"
            # mode, which the app supports deliberately -- those jobs live under
            # CLIENT_TMP/nologin and belong to nobody.
            #
            # user_id == "0" used to be accepted here unconditionally, with the
            # comment "TODO: security breach? (== 0)". It was: UserDAO assigned
            # IDs as len(userCollection), so the first person to register got
            # userID 0, and from then on anyone could act as that account by
            # sending the cookie userID=0 with any token at all -- including
            # calling dm_delete_job. Verified against a running server before
            # removing. See UserDAO.getNextUserID, which no longer issues 0.
            if (user_id == 'None' and sessionToken == None):
                return True
            if (user_id == 'None' or sessionToken == None or sessionToken != self.logged_users.get(user_id)):
                raise CredentialException("[b]User not valid[/b]. It looks like your session is not valid, please log-in again.")

        def isValidAdminUser(self, user_id, user_name, sessionToken):
            self.isValidUser(user_id,sessionToken)

            # isValidUser deliberately lets the anonymous "nologin" case
            # through: the app supports jobs that belong to nobody. An
            # administrative route must not inherit that permissiveness.
            #
            # Without this check an unauthenticated request reached
            # UserDAO.findByID(None), which does int(user_id), and the request
            # failed with
            #     TypeError: int() argument must be ... not 'NoneType'
            # So access was refused only as a side effect of a crash rather
            # than by decision, and the reply handed an unauthenticated caller
            # a servlet file name and line number instead of saying what was
            # required. An unknown ID was the same story one line later, where
            # _user would be None and _user.userName raised AttributeError.
            if user_id is None or str(user_id) == 'None' or not user_name:
                raise CredentialException(
                    "[b]Administrator privileges required[/b]. Please log in with "
                    "an administrator account to use this feature.")

            _user = UserDAO().findByID(user_id)

            if _user is None or _user.userName != user_name or not (user_name in ADMIN_ACCOUNTS.split(",")):
                raise Exception("User not allowed")

        def getLoggedUsersCount(self):
            return len(self.logged_users)

        def isLoggedUser(self, user_id):
            if (user_id == None):
                return False
            return self.logged_users.get(str(user_id), None) != None

    # storage for the instance reference
    __instance = None

    def __init__(self):
        """ Create singleton instance """
        # Check whether we already have an instance
        if UserSessionManager.__instance is None:
            # Create and remember instance
            UserSessionManager.__instance = UserSessionManager.__impl()

        # Store instance reference as the only member in the handle
        self.__dict__['_UserSessionManager__instance'] = UserSessionManager.__instance

    def __getattr__(self, attr):
        """ Delegate access to implementation """
        return getattr(self.__instance, attr)

    def __setattr__(self, attr, value):
        """ Delegate access to implementation """
        return setattr(self.__instance, attr, value)
