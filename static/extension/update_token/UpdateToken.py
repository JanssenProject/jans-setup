from io.jans.service.cdi.util import CdiUtil
from io.jans.model.custom.script.type.token import UpdateTokenType
from io.jans.oxauth.service import SessionIdService
import java
import sys
import os

class UpdateToken(UpdateTokenType):
    def __init__(self, currentTimeMillis):
        self.currentTimeMillis = currentTimeMillis

    def init(self, customScript, configurationAttributes):
        print "Update token script. Initializing ..."
        print "Update token script. Initialized successfully"

        return True

    def destroy(self, configurationAttributes):
        print "Update token   script. Destroying ..."
        print "Update token    script. Destroyed successfully"
        return True

    def getApiVersion(self):
        return 11

    # Returns boolean, true - indicates that script applied changes
    # This method is called after adding headers and claims. Hence script can override them
    # Note :
    # jsonWebResponse - is JwtHeader, you can use any method to manipulate JWT
    # context is reference of org.gluu.oxauth.service.external.context.ExternalUpdateTokenContext (in https://github.com/GluuFederation/oxauth project, )
    def modifyIdToken(self, jsonWebResponse, context):
        print "Update token script. Modify idToken: %s" % jsonWebResponse
        try :
            sessionIdService = CdiUtil.bean(SessionIdService)
            sessionId = sessionIdService.getSessionByDn(context.getGrant().getSessionDn()) # fetch from persistence

            openbanking_intent_id = sessionId.getSessionAttributes().get("openbanking_intent_id")
            acr = sessionId.getSessionAttributes().get("acr_ob")

            #jsonWebResponse.getHeader().setClaim("custom_header_name", "custom_header_value")

            #custom claims
            jsonWebResponse.getClaims().setClaim("openbanking_intent_id", openbanking_intent_id)
            jsonWebResponse.getClaims().setClaim("acr", acr)

            #regular claims
            jsonWebResponse.getClaims().setClaim("sub", openbanking_intent_id)

            print "Update token script. After modify idToken: %s" % jsonWebResponse

            return True
        except:
            print "update token failure" , sys.exc_info()[1]
            return None
