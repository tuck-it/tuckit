from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Custom user model — defined from day 1 so real auth can extend it later."""

    pass
