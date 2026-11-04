from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.functional import cached_property


class PrivateStorage(FileSystemStorage):
    # Resolve the root at use time so override_settings(PRIVATE_MEDIA_ROOT=...) works in tests.
    @cached_property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    def _clear_cached_properties(self, setting, **kwargs):
        super()._clear_cached_properties(setting, **kwargs)
        if setting == 'PRIVATE_MEDIA_ROOT':
            self.__dict__.pop('base_location', None)
            self.__dict__.pop('location', None)

    # FileSystemStorage falls back to MEDIA_URL when base_url is unset, so refuse explicitly.
    def url(self, name):
        raise ValueError('Private files have no URL; serve them through an authorised view.')


private_storage = PrivateStorage()


def get_private_storage():
    # A callable keeps the machine-specific PRIVATE_MEDIA_ROOT out of migrations.
    return private_storage
