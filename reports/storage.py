from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    # FileSystemStorage falls back to MEDIA_URL when base_url is unset, so refuse explicitly.
    def url(self, name):
        raise ValueError('Private files have no URL; serve them through an authorised view.')


private_storage = PrivateStorage(location=settings.PRIVATE_MEDIA_ROOT)


def get_private_storage():
    # A callable keeps the machine-specific PRIVATE_MEDIA_ROOT out of migrations.
    return private_storage
