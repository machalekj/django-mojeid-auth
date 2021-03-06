#!/usr/bin/python
# -*- coding: utf-8 -*-

# django-mojeid - mojeID integration for django
#
# Copyright (C) 2013 CZ.NIC
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

from django.conf import settings
from django.core.exceptions import FieldError, ImproperlyConfigured
from django.http import Http404
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ugettext

from openid.extensions import ax

from django_mojeid.exceptions import RequiredAttributeNotReturned

MOJEID_ENDPOINT_URL = 'https://mojeid.fred.nic.cz/endpoint/'
MOJEID_REGISTRATION_URL = 'https://mojeid.fred.nic.cz/registration/endpoint/'


def get_attributes(attribute_set):

    default = getattr(settings, 'MOJEID_ATTRIBUTES', [])
    res = getattr(settings, 'MOJEID_ATTRIBUTES_SETS', {})

    # MOJEID_ATTRIBUTES are default when present
    if default or not res:
        res['default'] = default

    try:
        return res[attribute_set]
    except KeyError:
        raise Http404


def get_attribute_query(attribute_set='defualt'):
    """ Return attributes without duplicities """
    attributes = get_attributes(attribute_set)

    used_dict = {}
    filtered_attributes = []
    for attribute in attributes:

        required = attribute.required
        attribute = attribute.attribute if attribute.type == 'handler' else attribute

        if attribute.code in used_dict:
            if not filtered_attributes[used_dict[attribute.code]][1]:
                # required=true has higher priority
                filtered_attributes[used_dict[attribute.code]] = (attribute, required, )
        else:
            used_dict[attribute.code] = len(filtered_attributes)
            filtered_attributes.append((attribute, required, ))

    return filtered_attributes


class CustomHandler(object):
    type = 'handler'

    def __init__(self, attribute, name, required=True):
        self.name = name
        self.required = required
        self.attribute = attribute


class MojeIDAttribute(object):
    type = 'attribute'

    code = None
    schema = None
    text = None

    def __init__(self, modelApp, modelClass, modelAttribute,
                 user_id_field_name='user_id', required=True,
                 updatable=False, use_for_registration=True):
        self.modelClass = modelClass
        self.modelApp = modelApp
        self.modelAttribute = modelAttribute
        self.user_id_field_name = user_id_field_name
        self.required = required
        self.updatable = updatable
        self.use_for_registration = use_for_registration
        self._model = None

    @property
    def model(self):
        if not self._model:
            # Import model during runtime
            from django.db.models.loading import get_model
            # set the model
            self._model = get_model(self.modelApp, self.modelClass)
            if not self._model:
                raise ImproperlyConfigured(_("Model '%(model)s' from App '%(app)s' does not exist.")
                                           % {'model': self.modelClass, 'app': self.modelApp})
        return self._model

    # This method could be overwritten using inheritance
    def _set(self, record, attribute, value):
        # Simply just set the attribute
        setattr(record, attribute, value)

    # This method could be overwritten using inheritance
    def _get_record(self, id):
        packed = {self.user_id_field_name: id}
        return self.model.objects.get(**packed)

    # This method could be overwritten using inheritance
    @classmethod
    def _get_value(cls, response):
        return response.getSingle(cls.schema, None)

    def set_model_value(self, id, value):
        record = self._get_record(id)
        if not hasattr(record, self.modelAttribute):
            raise FieldError(_("Cannot resolve keyword '%(model)s' into field. Choices are: %(choices)s")
                             % {"model": self.modelAttribute, "choices": ", ".join(record._meta._name_map.keys())})
        self._set(record, self.modelAttribute, value)
        record.save()

    # This method could be overwritten using inheritance
    def _get_model_value(self, id):
        return getattr(self._get_record(id), self.modelAttribute)

    @classmethod
    def generate_ax_attrinfo(cls, required):
        return ax.AttrInfo(cls.schema, alias=cls.code, required=required)

    @classmethod
    def get_value(cls, response, required):
        value = cls._get_value(response)
        if required and value is None:
            raise RequiredAttributeNotReturned(
                ugettext("Required Attribute '%(code)s' (%(text)s) was not returned.")
                % {"code": unicode(cls.code), "text": unicode(cls.text)}
            )
        return value

    def registration_form_attrs(self, id):
        # Return none if registration field is not present
        if not hasattr(self, 'registration_field') or not self.use_for_registration:
            return None

        value = self._get_model_value(id)
        # No value present
        if value is None:
            return None

        return {'name': self.registration_field, 'label': self.text.decode('utf-8'), 'value': value}

    # This method could be overwritten using inheritance
    def _get_form_html_template(self):
        return u'<label for="%s">%s</label><input type="text" name="%s" value="%s">'

    def registration_form_attrs_html(self, id):

        field = self.registration_form_attrs(id)

        # Field was not obtained.
        if not field:
            return ""

        return self._get_form_html_template() % (
            field['name'], field['label'], field['name'], field['value']
        )


class MojeIDBooleanAttribute(MojeIDAttribute):

    @classmethod
    def _get_value(self, response):
        res = response.getSingle(self.schema, None)
        if res is None:
            return None
        return True if res.lower() == 'true' else False


class BirthDate(MojeIDAttribute):
    code = 'birthdate'
    schema = 'http://axschema.org/birthDate'
    text = _(u'Birth Date')  # 'Datum Narození'
    registration_field = 'birth_date'


class FullName(MojeIDAttribute):
    code = 'fullname'
    schema = 'http://axschema.org/namePerson'
    text = _(u'Full Name')  # 'Celé jméno'


class FirstName(MojeIDAttribute):
    code = 'firstname'
    schema = 'http://axschema.org/namePerson/first'
    text = _(u'First Name')  # 'Jméno'
    registration_field = 'first_name'


class LastName(MojeIDAttribute):
    code = 'lastname'
    schema = 'http://axschema.org/namePerson/last'
    text = _(u'Last Name')  # 'Příjmení'
    registration_field = 'last_name'


class NickName(MojeIDAttribute):
    code = 'nick'
    schema = 'http://axschema.org/namePerson/friendly'
    text = _(u'Nick Name')  # 'Přezdívka'
    registration_field = 'username'


class Company(MojeIDAttribute):
    code = 'company'
    schema = 'http://axschema.org/company/name'
    text = _(u'Company')  # 'Jméno společnosti'
    registration_field = 'organization'


class HomeAddress(MojeIDAttribute):
    code = 'h_address'
    schema = 'http://axschema.org/contact/postalAddress/home'
    text = _(u'Home Address – Street')  # 'Domácí adresa – Ulice'
    registration_field = 'address__default__street1'


class HomeAddress2(MojeIDAttribute):
    code = 'h_address2'
    schema = 'http://axschema.org/contact/postalAddressAdditional/home'
    text = _(u'Home Address – Street2')  # 'Domácí adresa – Ulice2'
    registration_field = 'address__default__street2'


class HomeAddress3(MojeIDAttribute):
    code = 'h_address3'
    schema = 'http://specs.nic.cz/attr/addr/main/street3'
    text = _(u'Home Address – Street3')  # 'Domácí adresa – Ulice3'
    registration_field = 'address__default__street3'


class HomeCity(MojeIDAttribute):
    code = 'h_city'
    schema = 'http://axschema.org/contact/city/home'
    text = _(u'Home Address – City')  # 'Domácí adresa – Město'
    registration_field = 'address__default__city'


class HomeState(MojeIDAttribute):
    code = 'h_state'
    schema = 'http://axschema.org/contact/state/home'
    text = _(u'Home Address – State')  # 'Domácí adresa – Stát'
    registration_field = 'address__default__state'


class HomeCountry(MojeIDAttribute):
    code = 'h_country'
    schema = 'http://axschema.org/contact/country/home'
    text = _(u'Home Address – Country')  # 'Domácí adresa – Země'
    registration_field = 'address__default__country'


class HomePostCode(MojeIDAttribute):
    code = 'h_postcode'
    schema = 'http://axschema.org/contact/postalCode/home'
    text = _(u'Home Address – Country')  # 'Domácí adresa – PSČ'
    registration_field = 'address__default__postal_code'


class BillingAddress(MojeIDAttribute):
    code = 'b_address'
    schema = 'http://specs.nic.cz/attr/addr/bill/street'
    text = _(u'Billing Address – Street')  # 'Faktur. adresa – Ulice'
    registration_field = 'address__billing__street1'


class BillingAddress2(MojeIDAttribute):
    code = 'b_address2'
    schema = 'http://specs.nic.cz/attr/addr/bill/street2'
    text = _(u'Billing Address – Street2')  # 'Faktur. adresa – Ulice2'
    registration_field = 'address__billing__street2'


class BillingAddress3(MojeIDAttribute):
    code = 'b_address3'
    schema = 'http://specs.nic.cz/attr/addr/bill/street3'
    text = _(u'Billing Address – Street3')  # 'Faktur. adresa – Ulice3'
    registration_field = 'address__billing__street3'


class BillingCity(MojeIDAttribute):
    code = 'b_city'
    schema = 'http://specs.nic.cz/attr/addr/bill/city'
    text = _(u'Billing Address – City')  # 'Faktur. adresa – Město'
    registration_field = 'address__billing__city'


class BillingState(MojeIDAttribute):
    code = 'b_state'
    schema = 'http://specs.nic.cz/attr/addr/bill/sp'
    text = _(u'Billing Address – State')  # 'Faktur. adresa – Stát'
    registration_field = 'address__billing__state'


class BillingCountry(MojeIDAttribute):
    code = 'b_country'
    schema = 'http://specs.nic.cz/attr/addr/bill/cc'
    text = _(u'Billing Address – Country')  # 'Faktur. adresa – Země'
    registration_field = 'address__billing__country'


class BillingPostCode(MojeIDAttribute):
    code = 'b_postcode'
    schema = 'http://specs.nic.cz/attr/addr/bill/pc'
    text = _(u'Billing Address – Postal Code')  # 'Faktur. adresa – PSČ'
    registration_field = 'address__billing__postal_code'


class ShippingAddress(MojeIDAttribute):
    code = 's_address'
    schema = 'http://specs.nic.cz/attr/addr/ship/street'
    text = _(u'Shipping Address – Street')  # 'Doruč. adresa – Ulice'
    registration_field = 'address__shipping__street1'


class ShippingAddress2(MojeIDAttribute):
    code = 's_address2'
    schema = 'http://specs.nic.cz/attr/addr/ship/street2'
    text = _(u'Shipping Address – Street2')  # 'Doruč. adresa – Ulice2'
    registration_field = 'address__shipping__street2'


class ShippingAddress3(MojeIDAttribute):
    code = 's_address3'
    schema = 'http://specs.nic.cz/attr/addr/ship/street3'
    text = _(u'Shipping Address – Street3')  # 'Doruč. adresa – Ulice3'
    registration_field = 'address__shipping__street3'


class ShippingCity(MojeIDAttribute):
    code = 's_city'
    schema = 'http://specs.nic.cz/attr/addr/ship/city'
    text = _(u'Shipping Address – City')  # 'Doruč. adresa – Město'
    registration_field = 'address__shipping__city'


class ShippingState(MojeIDAttribute):
    code = 's_state'
    schema = 'http://specs.nic.cz/attr/addr/ship/sp'
    text = _(u'Shipping Address – State')  # 'Doruč. adresa – Stát'
    registration_field = 'address__shipping__state'


class ShippingCountry(MojeIDAttribute):
    code = 's_country'
    schema = 'http://specs.nic.cz/attr/addr/ship/cc'
    text = _(u'Shipping Address – Country')  # 'Doruč. adresa – Země'
    registration_field = 'address__shipping__country'


class ShippingPostCode(MojeIDAttribute):
    code = 's_postcode'
    schema = 'http://specs.nic.cz/attr/addr/ship/pc'
    text = _(u'Shipping Address – Postal Code')  # 'Doruč. adresa – PSČ'
    registration_field = 'address__shipping__postal_code'


class MailingAddress(MojeIDAttribute):
    code = 'm_address'
    schema = 'http://specs.nic.cz/attr/addr/mail/street'
    text = _(u'Mailing Address – Street')  # 'Koresp. adresa – Ulice'
    registration_field = 'address__mailing__street1'


class MailingAddress2(MojeIDAttribute):
    code = 'm_address2'
    schema = 'http://specs.nic.cz/attr/addr/mail/street2'
    text = _(u'Mailing Address – Street2')  # 'Koresp. adresa – Ulice2'
    registration_field = 'address__mailing__street2'


class MailingAddress3(MojeIDAttribute):
    code = 'm_address3'
    schema = 'http://specs.nic.cz/attr/addr/mail/street3'
    text = _(u'Mailing Address – Street3')  # 'Koresp. adresa – Ulice3'
    registration_field = 'address__mailing__street3'


class MailingCity(MojeIDAttribute):
    code = 'm_city'
    schema = 'http://specs.nic.cz/attr/addr/mail/city'
    text = _(u'Mailing Address – City')  # 'Koresp. adresa – Město'
    registration_field = 'address__mailing__city'


class MailingState(MojeIDAttribute):
    code = 'm_state'
    schema = 'http://specs.nic.cz/attr/addr/mail/sp'
    text = _(u'Mailing Address – State')  # 'Koresp. adresa – Stát'
    registration_field = 'address__mailing__state'


class MailingCountry(MojeIDAttribute):
    code = 'm_country'
    schema = 'http://specs.nic.cz/attr/addr/mail/cc'
    text = _(u'Mailing Address – Country')  # 'Koresp. adresa – Země'
    registration_field = 'address__mailing__country'


class MailingPostCode(MojeIDAttribute):
    code = 'm_postcode'
    schema = 'http://specs.nic.cz/attr/addr/mail/pc'
    text = _(u'Mailing Address – Postal Code')  # 'Koresp. adresa – PSČ'
    registration_field = 'address__mailing__postal_code'


class Phone(MojeIDAttribute):
    code = 'phone'
    schema = 'http://axschema.org/contact/phone/default'
    text = _(u'Phone – Default')  # 'Telefon – Hlavní'
    registration_field = 'phone__default__number'


class PhoneHome(MojeIDAttribute):
    code = 'phone_home'
    schema = 'http://axschema.org/contact/phone/home'
    text = _(u'Phone – Home')  # 'Telefon – Domácí'
    registration_field = 'phone__home__number'


class PhoneWork(MojeIDAttribute):
    code = 'phone_work'
    schema = 'http://axschema.org/contact/phone/business'
    text = _(u'Phone – Work')  # 'Telefon – Pracovní'
    registration_field = 'phone__office__number'


class PhoneMobile(MojeIDAttribute):
    code = 'phone_mobile'
    schema = 'http://axschema.org/contact/phone/cell'
    text = _(u'Phone – Mobile')  # 'Telefon – Mobil'
    registration_field = 'phone__mobile__number'


class Fax(MojeIDAttribute):
    code = 'fax'
    schema = 'http://axschema.org/contact/phone/fax'
    text = _(u'Fax')  # 'Telefon – Fax'


class Email(MojeIDAttribute):
    code = 'email'
    schema = 'http://axschema.org/contact/email'
    text = _(u'Email – Default')  # 'Email – Hlavní'
    registration_field = 'email__default__email'


class Email2(MojeIDAttribute):
    code = 'email2'
    schema = 'http://specs.nic.cz/attr/email/notify'
    text = _(u'Email – Notify')  # 'Email – Notifikační'
    registration_field = 'email__notify__email'


class Email3(MojeIDAttribute):
    code = 'email3'
    schema = 'http://specs.nic.cz/attr/email/next'
    text = _(u'Email – Other')  # 'Email – Další'
    registration_field = 'email__next__email'


class Url(MojeIDAttribute):
    code = 'url'
    schema = 'http://axschema.org/contact/web/default'
    text = _(u'URL – Default')  # 'URL – Hlavní'
    registration_field = 'urladdress__main__url'


class Blog(MojeIDAttribute):
    code = 'blog'
    schema = 'http://axschema.org/contact/web/blog'
    text = _(u'URL – Blog')  # 'URL – Blog'
    registration_field = 'urladdress__blog__url'


class Url2(MojeIDAttribute):
    code = 'url2'
    schema = 'http://specs.nic.cz/attr/url/personal'
    text = _(u'URL – Personal')  # 'URL – Osobní'
    registration_field = 'urladdress__personal__url'


class Url3(MojeIDAttribute):
    code = 'url3'
    schema = 'http://specs.nic.cz/attr/url/work'
    text = _(u'URL – Work')  # 'URL – Pracovní'
    registration_field = 'urladdress__office__url'


class RSS(MojeIDAttribute):
    code = 'rss'
    schema = 'http://specs.nic.cz/attr/url/rss'
    text = _(u'URL – RSS')  # 'URL – RSS'
    registration_field = 'urladdress__rss__url'


class Facebook(MojeIDAttribute):
    code = 'fb'
    schema = 'http://specs.nic.cz/attr/url/facebook'
    text = _(u'URL – Facebook')  # 'URL – Facebook'
    registration_field = 'urladdress__facebook__url'


class Twitter(MojeIDAttribute):
    code = 'twitter'
    schema = 'http://specs.nic.cz/attr/url/twitter'
    text = _(u'URL – Twitter')  # 'URL – Twitter'
    registration_field = 'urladdress__twitter__url'


class LinkedIn(MojeIDAttribute):
    code = 'linkedin'
    schema = 'http://specs.nic.cz/attr/url/linkedin'
    text = _(u'URL – LinkedIN')  # 'URL – LinkedIN'
    registration_field = 'urladdress__linkedin__url'


class ICQ(MojeIDAttribute):
    code = 'icq'
    schema = 'http://axschema.org/contact/IM/ICQ'
    text = _(u'IM – ICQ')  # 'IM – ICQ'
    registration_field = 'imaccount__icq__username'


class Jabber(MojeIDAttribute):
    code = 'jabber'
    schema = 'http://axschema.org/contact/IM/Jabber'
    text = _(u'IM – Jabber')  # 'IM – Jabber'
    registration_field = 'imaccount__jabber__username'


class Skype(MojeIDAttribute):
    code = 'skype'
    schema = 'http://axschema.org/contact/IM/Skype'
    text = _(u'IM – Skype')  # 'IM – Skype'
    registration_field = 'imaccount__skype__username'


class GoogleTalk(MojeIDAttribute):
    code = 'gtalk'
    schema = 'http://specs.nic.cz/attr/im/google_talk'
    text = _(u'IM – Google Talk')  # 'IM – Google Talk'
    registration_field = 'imaccount__google_talk__username'


class WindowsLive(MojeIDAttribute):
    code = 'wlive'
    schema = 'http://specs.nic.cz/attr/im/windows_live'
    text = _(u'IM – Windows Live')  # 'IM – Windows Live'
    registration_field = 'imaccout__windows_live__username'


class ICO(MojeIDAttribute):
    code = 'vat_id'
    schema = 'http://specs.nic.cz/attr/contact/ident/vat_id'
    text = _(u'Identifier – VAT Identification Number')  # 'Identifikátor – ICO'
    registration_field = 'vat_id_num'


class DIC(MojeIDAttribute):
    code = 'vat'
    schema = 'http://specs.nic.cz/attr/contact/vat'
    text = _(u'Identifier – VAT registration Number')  # 'Identifikátor – DIC'
    registration_field = 'vat_reg_num'


class IdentityCard(MojeIDAttribute):
    code = 'op'
    schema = 'http://specs.nic.cz/attr/contact/ident/card'
    text = _(u'Identifier – ID Card')  # 'Identifikátor – OP'
    registration_field = 'id_card_num'


class Passport(MojeIDAttribute):
    code = 'pas'
    schema = 'http://specs.nic.cz/attr/contact/ident/pass'
    text = _(u'Identifier – Passport')  # 'Identifikátor – PAS'
    registration_field = 'passport_num'


class MPSV(MojeIDAttribute):
    code = 'mpsv'
    schema = 'http://specs.nic.cz/attr/contact/ident/ssn'
    text = _(u'Identifier – MPSV')  # 'Identifikátor – MPSV'
    registration_field = 'ssn_id_num'


class Student(MojeIDBooleanAttribute):
    code = 'student'
    schema = 'http://specs.nic.cz/attr/contact/student'
    text = _(u'Flag – Student')  # 'Příznak – Student'


class Validated(MojeIDBooleanAttribute):
    # Probably not supported anymore
    code = 'validated'
    schema = 'http://specs.nic.cz/attr/contact/valid'
    text = _(u'Flag – Validation')  # 'Příznak – Validace'


class Status(MojeIDAttribute):
    # Probably not supported anymore
    code = 'status'
    schema = 'http://specs.nic.cz/attr/contact/status'
    text = _(u'Account State')  # 'Stav účtu'


class Adult(MojeIDBooleanAttribute):
    code = 'adult'
    schema = 'http://specs.nic.cz/attr/contact/adult'
    text = _(u'Flag – Adult')  # 'Příznak – Starší 18 let'


class Image(MojeIDAttribute):
    code = 'image'
    schema = 'http://specs.nic.cz/attr/contact/image'
    text = _(u'Image (base64)')  # 'Obrázek (base64)'


class Assertion:

    # Status codes for the assertions
    class StatusCodes:
        _codes = [
            'REGISTERED',
            'CONDITIONALLY_IDENTIFIED',
            'IDENTIFIED',
            'VALIDATED',
        ]

        class __metaclass__(type):
            def __iter__(self):
                for attr in self._codes:
                    yield attr

            def __getattr__(self, name):
                if name not in self._codes:
                    raise AttributeError(_("class %(class)s has no attribute '%(attr)s'") %
                                         {"class": self.__name__, "attr": name})
                return name

    #Error strings
    class ErrorString:
        BAD_REQUEST = _('Bad request.')
        MISSING_STATUS = _('Status is missing.')
        INVALID_STATUS = _('Status is invalid.')
        MISSING_CLAIMED_ID = _('Claimed ID is missing.')
        MISSING_NONCE = _('Registration nonce is missing.')
        INVALID_NONCE = _('Registration nonce is invalid.')

# OpenID logging to django debug
import logging
logger = logging.getLogger('openid')
from openid import oidutil
oidutil.log = logger.warn
