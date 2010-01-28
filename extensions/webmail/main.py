# -*- coding: utf-8 -*-
import time
import sys
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import simplejson
from django.utils.translation import ugettext as _
from django.core.urlresolvers import reverse
from django.conf.urls.defaults import include
from django.contrib.auth.decorators import login_required
from mailng.admin.models import Mailbox
from mailng.lib import events, parameters, _render
from mailng.lib.email_listing import Email
from imap_listing import *
from forms import *
from templatetags.webextras import *

def init():
    events.register("UserMenuDisplay", menu)
    events.register("UserLogin", userlogin)
    parameters.register("webmail", "IMAP_SERVER", "string", "127.0.0.1",
                        help=_("Address of your IMAP server"))
    parameters.register("webmail", "SMTP_SERVER", "string", "127.0.0.1",
                        help=_("Address of your SMTP server"))

def urls():
    return (r'^mailng/webmail/',
            include('mailng.extensions.webmail.urls'))

def menu(**kwargs):
    if kwargs["target"] != "user_menu_box":
        return []
    return [
        {"name" : _("Webmail"),
         "url" : reverse(index),
         "img" : "/static/pics/webmail.png"}
        ]

def userlogin(**kwargs):
    kwargs["request"].session["password"] = kwargs["password"]

def getctx(status, level=1, **kwargs):
    callername = sys._getframe(level).f_code.co_name
    ctx = {"status" : status, "callback" : callername}
    for kw, v in kwargs.iteritems():
        ctx[kw] = v
    return ctx

@login_required
def folder(request, name, updatenav=True):
    if not name:
        name = "INBOX"
    if updatenav:
        pageid = request.GET.has_key("page") and int(request.GET["page"]) or 1
        request.session["folder"] = name
        request.session["page"] = pageid
    lst = ImapListing(request.user.username, request.session["password"],
                      name, folder=name)
    page = lst.paginator.getpage(request.session["page"])
    if page:
        content = lst.fetch(request, page.id_start, page.id_stop)
        navbar = lst.render_navbar(page)
    else:
        content = "Empty folder"
        navbar = ""
    ctx = getctx("ok", listing=content, navbar=navbar,
                 menu=listing_menu("", name, request.user.get_all_permissions()))
    return HttpResponse(simplejson.dumps(ctx), mimetype="application/json")

@login_required
def index(request):
    lst = ImapListing(request.user.username, request.session["password"],
                      "INBOX", folder="INBOX")
    return lst.render(request, empty=True)

def fetchmail(request, folder, mail_id, all=False):
    res = IMAPconnector(request).fetch(start=mail_id, folder=folder, all=all)
    if len(res):
        return res[0]
    return None

@login_required
def viewmail(request, folder, mail_id=None):
    header = fetchmail(request, folder, mail_id)
    if header:
        from templatetags.webextras import viewm_menu
        pageid = request.session.has_key("page") and request.session["page"] or "1"
        menu = viewm_menu("", folder, mail_id, pageid,
                          request.user.get_all_permissions())
        folder, imapid = header["imapid"].split("/")
        mailcontent = render_to_string("webmail/viewmail.html", {
                "header" : header, "folder" : folder, "imapid" : imapid
                })
        ctx = getctx("ok", menu=menu, listing=mailcontent)
        return HttpResponse(simplejson.dumps(ctx), mimetype="application/json")

@login_required
def getmailcontent(request, folder, mail_id):
    from mailng.lib.email_listing import Email

    msg = fetchmail(request, folder, mail_id, True)
    if "class" in msg.keys() and msg["class"] == "unseen":
        IMAPconnector(request).msgseen(msg["imapid"])
    email = Email(msg, mode="html", links="1")
    return email.render(request)

@login_required
def move(request):
    for arg in ["msgset", "to"]:
        if not request.GET.has_key(arg):
            return
    folder, id = request.GET["msgset"].split("/")
    mbc = IMAPconnector(request)
    mbc.move(id, folder, request.GET["to"])
    return HttpResponse(simplejson.dumps({"status" : "ok"}),
                        mimetype="application/json")

@login_required
def empty(request, name):
    mbc = IMAPconnector(request)
    mbc.empty(name)
    return folder(request, name, False)

def render_compose(request, form, bodyheader=None, body=None):
    menu = compose_menu("", request.session["folder"], request.session["page"], 
                        request.user.get_all_permissions())
    content = render_to_string("webmail/compose.html", {
            "form" : form, "bodyheader" : bodyheader, "body" : body
            })
    ctx = getctx("ok", level=2, menu=menu, listing=content)
    return HttpResponse(simplejson.dumps(ctx), mimetype="application/json")

@login_required
def compose(request):
    if request.method == "POST":
        form = ComposeMailForm(request.POST)
        if form.is_valid():
            from email.mime.text import MIMEText
            import smtplib

            msg = MIMEText(request.POST["id_body"].encode("utf-8"), 
                           _charset="utf-8")
            msg["Subject"] = request.POST["subject"]
            msg["From"] = request.POST["from_"]
            msg["to"] = request.POST["to"]
            s = smtplib.SMTP(parameters.get("webmail", "SMTP_SERVER"))
            s.sendmail(msg['From'], [msg['To']], msg.as_string())
            s.quit()
            return folder(request, request.session["folder"], False)

    form = ComposeMailForm()
    form.fields["from_"].initial = request.user.username
    return render_compose(request, form)

@login_required
def reply(request, folder, mail_id):
    if request.method == "POST":
        return
    msg = fetchmail(request, folder, mail_id, True)
    email = Email(msg)
    lines = email.body.split('\n')
    body = ""
    for l in lines:
        if body != "":
            body += "\n"
        body += ">%s" % l
    form = ComposeMailForm()
    form.fields["from_"].initial = request.user.username
    form.fields["to"].initial = msg["From"]
    m = re.match("re\s*:\s*.+", msg["Subject"].lower())
    if m:
        form.fields["subject"].initial = msg["Subject"]
    else:
        form.fields["subject"].initial = "Re: %s" % msg["Subject"]
    textheader = msg["From"] + " " + _("wrote:")
    return render_compose(request, form, textheader, body)
