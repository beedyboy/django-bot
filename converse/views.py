import json
import logging
import traceback

from django.conf import settings
from django.http.response import HttpResponseRedirect, HttpResponse
from django.urls import reverse
from django.views.generic.base import View, TemplateView
from slackclient import SlackClient

from converse.tasks import slack_message_event, slack_action_event
from converse.models import SlackAuth
from converse.tasks import retrieve_channel_users

logger = logging.getLogger(__name__)


# https://slack.com/oauth/authorize?scope=bot&client_id=85403973076.103667105557&redirect_uri=https://b7f3301c.ngrok.io/converse/slack/oauth

def get_slack_oauth_uri(request):
    # scope = "bot+channels:write"
    scope = "bot"
    return "https://slack.com/oauth/authorize?scope=" + scope + "&client_id=" + settings.SLACK_CLIENT_ID + \
           "&redirect_uri=" + request.build_absolute_uri(reverse("converse:slack:oauth"))


class SlackOAuthView(View):
    def dispatch(self, request, *args, **kwargs):
        try:
            code = request.GET.get('code', '')
            sc = SlackClient("")
            result = sc.api_call("oauth.access", client_id=settings.SLACK_CLIENT_ID,
                                 client_secret=settings.SLACK_CLIENT_SECRET, code=code,
                                 redirect_uri=request.build_absolute_uri(reverse('converse:slack:oauth')))
            if SlackAuth.objects.filter(team_id=result["team_id"]).exists():
                SlackAuth.objects.get(team_id=result["team_id"]).delete()
            slack_auth = SlackAuth.objects.create(access_token=result["access_token"], team_id=result["team_id"],
                                                  team_name=result["team_name"], bot_id=result["bot"]["bot_user_id"],
                                                  bot_access_token=result["bot"]["bot_access_token"])
            retrieve_channel_users.delay(slack_auth.pk)
            return HttpResponseRedirect("http://talkai.xyz/success.html")
        except Exception as e:
            logger.error(traceback.format_exc())
            return HttpResponseRedirect("http://talkai.xyz/failure.html")


class SlackActionView(View):
    def dispatch(self, request, *args, **kwargs):
        try:
            query = request.POST
            logger.debug(str(query))
        except Exception:
            logger.error(traceback.format_exc())
        return HttpResponse(status=200)


class SlackActionURL(View):
    def post(self, request):
        try:
            query = json.loads(request.POST["payload"])
            logger.debug(str(query))
        except Exception:
            logger.error(traceback.format_exc())
            return HttpResponse(status=400)
        if settings.SLACK_VERIFICATION_TOKEN != query["token"]:
            return HttpResponse(status=400)
        slack_action_event.delay(query)
        return HttpResponse(status=200)


class SlackRequestURL(View):
    def post(self, request):
        try:
            query = json.loads(request.body)
            logger.debug(str(query))
        except Exception:
            logger.error(traceback.format_exc())
            return HttpResponse(status=400)
        if settings.SLACK_VERIFICATION_TOKEN != query["token"]:
            return HttpResponse(status=400)
        if query["type"] == "url_verification":
            return HttpResponse(status=200, content=query["challenge"])
        if query["type"] == "event_callback":
            event = query["event"]
            if event["type"] == "message" and "bot_id" not in event:
                slack_message_event.delay(query["team_id"], event)
        return HttpResponse(status=200)