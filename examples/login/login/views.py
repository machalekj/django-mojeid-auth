from django.contrib.auth import logout
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.dispatch import receiver
from django.shortcuts import render, redirect
from django.http import QueryDict

from django_mojeid.auth import OpenIDBackend
from django_mojeid.models import UserOpenID
from django_mojeid.signals import authenticate_user


def login(request):
    """ Display the login page """

    # Auto logout
    logout(request)

    return render(request, 'login.html', {'why_my_id_url': 'https://www.nic.cz/'})


def new_user(request):
    """ Display new user form """
    return render(request, 'new_user.html', dict(request.GET))


@login_required
def display_user(request):
    """ Display existing user """
    return render(request, 'existing_user.html', dict(request.GET))


# This overrides a part of the default mojeID login_complete logic
@receiver(authenticate_user, dispatch_uid="mojeid_create_user")
def authenticate_user(**kwargs):
    """ Display user forms prefilled with data from mojeID """
    request = kwargs['request']
    openid_response = kwargs['openid_response']
    redirect_to = kwargs['redirect']
    user_model = get_user_model()

    # Get the user
    try:
        # Authenticate user
        user_openid = UserOpenID.objects.get(
            claimed_id__exact=openid_response.identity_url)
        try:
            user = user_model.objects.get(pk=user_openid.user_id)
            if OpenIDBackend.is_user_authenticated(user):
                OpenIDBackend.associate_user_with_session(request, user)
        except user_model.DoesNotExist:
            pass

        # Update all updatable attributes
        #attrs = OpenIDBackend.update_user_from_openid(user_id, openid_response)
        # Or Just display the updatable attributes to be updated
        attrs = OpenIDBackend.get_model_changes(openid_response, only_updatable=True)

        # Set url path
        path = reverse(display_user)

    except UserOpenID.DoesNotExist:
        # Create user

        # Get attributes for the new User model
        attrs = OpenIDBackend.get_model_changes(openid_response)

        # Set url path
        path = reverse(new_user)

    # set the params for redirect
    qd = QueryDict('').copy()
    params = attrs.get(get_user_model(), {})
    params['next'] = redirect_to
    if 'user_id_field_name' in params:
        del params['user_id_field_name']
    qd.update(params)
    # TODO claimed_id as a param!

    url = "%s?%s" % (path, qd.urlencode())
    return redirect(url)
