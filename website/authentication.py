from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailAuthenticationBackend(ModelBackend):
    """
    Authenticate TheStoreWare users using their registered email address.

    The existing Django User model remains unchanged for now.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = kwargs.get("email") or username

        if not email or not password:
            return None

        email = email.strip().lower()
        UserModel = get_user_model()

        try:
            user = UserModel.objects.get(email__iexact=email)
        except UserModel.DoesNotExist:
            # Run password hashing once to reduce account-enumeration timing differences.
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            # Email addresses must be unique for TheStoreWare authentication.
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None