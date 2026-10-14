from django.contrib.auth.views import LoginView


class UserLoginView(LoginView):
    template_name = "registration/user_login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        next_url = self.get_redirect_url()

        if next_url:
            return next_url

        return "/"