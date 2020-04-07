import logging

import requests

from bauh.api.http import HttpClient


def is_available(client: HttpClient, logger: logging.Logger) -> bool:
    try:
        client.exists('https://google.com', session=False)
        return True
    except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
        if logger:
            logger.warning('Internet connection seems to be off: {}'.format(e.__class__.__name__))
        return False

