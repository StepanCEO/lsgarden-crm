import base64
import logging
import socket

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend

logger = logging.getLogger(__name__)


class XOAuth2EmailBackend(EmailBackend):
    def open(self):
        if self.connection:
            return False
        if self._partial_connection is not None:
            self._close_connection(self._partial_connection)
            self._partial_connection = None

        connection_params = {"local_hostname": socket.getfqdn()}
        if self.timeout is not None:
            connection_params["timeout"] = self.timeout
        if self.use_ssl:
            connection_params["context"] = self.ssl_context
        try:
            self._partial_connection = self.connection_class(
                self.host, self.port, **connection_params
            )
            self._partial_connection.ehlo_or_helo_if_needed()

            if not self.use_ssl and self.use_tls:
                self._partial_connection.starttls(context=self.ssl_context)
                self._partial_connection.ehlo_or_helo_if_needed()

            token = settings.EMAIL_OAUTH_TOKEN
            authenticated = False
            if token:
                try:
                    auth_str = f"user={self.username}\x01auth=Bearer {token}\x01\x01"
                    self._partial_connection.auth(
                        'XOAUTH2',
                        lambda challenge: auth_str,
                        initial_response_ok=True,
                    )
                    authenticated = True
                except Exception as e:
                    logger.warning('XOAUTH2 failed: %s, falling back to password', e)

            if not authenticated and self.username and self.password:
                self._partial_connection.login(self.username, self.password)
                authenticated = True

            if not authenticated:
                raise OSError('No authentication method succeeded')

            self.connection = self._partial_connection
            self._partial_connection = None
            return True
        except OSError:
            if not self.fail_silently:
                raise
