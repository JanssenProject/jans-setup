import os
import json
import zipfile
import re
import sys
import base64
import glob
import ldap3

from urllib.parse import urlparse
from ldap3.utils import dn as dnutils

from setup_app import paths
from setup_app import static
from setup_app.utils import base
from setup_app.config import Config
from setup_app.utils.db_utils import dbUtils
from setup_app.utils.setup_utils import SetupUtils
from setup_app.utils.properties_utils import propertiesUtils
from setup_app.pylib.jproperties import Properties
from setup_app.installers.jetty import JettyInstaller
from setup_app.installers.base import BaseInstaller

class CollectProperties(SetupUtils, BaseInstaller):


    def __init__(self):
        pass

    def collect(self):
        print("Please wait while collecting properties...")
        self.logIt("Previously installed instance. Collecting properties")
        salt_fn = os.path.join(Config.configFolder,'salt')
        if os.path.exists(salt_fn):
            salt_prop = base.read_properties_file(salt_fn)
            Config.encode_salt = salt_prop['encodeSalt']

        jans_prop = base.read_properties_file(Config.jans_properties_fn)
        Config.persistence_type = jans_prop['persistence.type']
        oxauth_ConfigurationEntryDN = jans_prop['jansAuth_ConfigurationEntryDN']
        jans_ConfigurationDN = 'ou=configuration,o=jans'

        jans_sql_prop = base.read_properties_file(Config.jansRDBMProperties)
        uri_re = re.match('jdbc:(.*?)://(.*?):(.*?)/(.*)', jans_sql_prop['connection.uri'])
        Config.rdbm_type, Config.rdbm_host, self.rdbm_port, self.rdbm_db = uri_re.groups()
        Config.rdbm_port = int(self.rdbm_port)
        Config.rdbm_install_type = static.InstallTypes.LOCAL if Config.rdbm_host == 'localhost' else static.InstallTypes.REMOTE
        Config.rdbm_user = jans_sql_prop['auth.userName']
        Config.rdbm_password_enc = jans_sql_prop['auth.userPassword']
        Config.rdbm_password = self.unobscure(Config.rdbm_password_enc)
        Config.rdbm_db = jans_sql_prop['db.schema.name']

        # It is time to bind database
        dbUtils.bind()
        
        if dbUtils.session:
            dbUtils.rdm_automapper()

        result = dbUtils.search('ou=clients,o=jans', search_filter='(&(inum=1701.*)(objectClass=jansClnt))')

        if result:
            Config.jans_radius_client_id = result['inum']
            Config.jans_ro_encoded_pw = result['jansClntSecret']
            Config.jans_ro_pw = self.unobscure(Config.jans_ro_encoded_pw)
    
            result = dbUtils.search('inum=5866-4202,ou=scripts,o=jans')
            if result:
                Config.enableRadiusScripts = result['jansEnabled']

            result = dbUtils.search('ou=clients,o=jans', search_filter='(&(inum=1402.*)(objectClass=jansClnt))')
            if result:
                Config.oxtrust_requesting_party_client_id = result['inum']

        oxConfiguration = dbUtils.search(jans_ConfigurationDN, search_filter='(objectClass=jansAppConf)')
        if 'jansIpAddress' in oxConfiguration:
            Config.ip = oxConfiguration['jansIpAddress']

        if isinstance(oxConfiguration['jansCacheConf'], str):
            oxCacheConfiguration = json.loads(oxConfiguration['jansCacheConf'])
        else:
            oxCacheConfiguration = oxConfiguration['jansCacheConf']
        
        Config.cache_provider_type = str(oxCacheConfiguration['cacheProviderType'])

        Config.scim_rp_client_jks_pass = 'secret' # this is static

        # Other clients
        client_var_id_list = [
                    ('oxauth_client_id', '1001.'),
                    ('jca_client_id', '1801.', {'pw': 'jca_client_pw', 'encoded':'jca_client_encoded_pw'}),
                    ]

        self.check_clients(client_var_id_list)

        result = dbUtils.search(
                        search_base='inum={},ou=clients,o=jans'.format(Config.oxauth_client_id),
                        search_filter='(objectClass=jansClnt)')


        Config.oxauthClient_encoded_pw = result['jansClntSecret']
        Config.oxauthClient_pw = self.unobscure(Config.oxauthClient_encoded_pw)

        dn_oxauth, oxAuthConfDynamic = dbUtils.get_oxAuthConfDynamic()

        o_issuer = urlparse(oxAuthConfDynamic['issuer'])
        Config.hostname = str(o_issuer.netloc)

        Config.oxauth_openidScopeBackwardCompatibility =  oxAuthConfDynamic.get('openidScopeBackwardCompatibility', False)

        if 'pairwiseCalculationSalt' in oxAuthConfDynamic:
            Config.pairwiseCalculationSalt =  oxAuthConfDynamic['pairwiseCalculationSalt']
        if 'legacyIdTokenClaims' in oxAuthConfDynamic:
            Config.oxauth_legacyIdTokenClaims = oxAuthConfDynamic['legacyIdTokenClaims']
        if 'pairwiseCalculationKey' in oxAuthConfDynamic:
            Config.pairwiseCalculationKey = oxAuthConfDynamic['pairwiseCalculationKey']
        if 'keyStoreFile' in oxAuthConfDynamic:
            Config.oxauth_openid_jks_fn = oxAuthConfDynamic['keyStoreFile']
        if 'keyStoreSecret' in oxAuthConfDynamic:
            Config.oxauth_openid_jks_pass = oxAuthConfDynamic['keyStoreSecret']

        ssl_subj = self.get_ssl_subject('/etc/certs/httpd.crt')
        Config.countryCode = ssl_subj['C']
        Config.state = ssl_subj['ST']
        Config.city = ssl_subj['L']
        Config.city = ssl_subj['L']
         
         #this is not good, but there is no way to retreive password from ldap
        if not Config.get('admin_password'):
            if Config.get('ldapPass'):
                Config.admin_password = Config.ldapPass
            elif Config.get('cb_password'):
                Config.admin_password = Config.cb_password

        if not Config.get('orgName'):
            Config.orgName = ssl_subj['O']

        #for service in jetty_services:
        #    setup_prop[jetty_services[service][0]] = os.path.exists('/opt/jans/jetty/{0}/webapps/{0}.war'.format(service))


        for s in ['jansScimEnabled']:
            setattr(Config, s, oxConfiguration.get(s, False))

        application_max_ram = 3072

        default_dir = '/etc/default'
        usedRatio = 0.001
        oxauth_max_heap_mem = 0

        jetty_services = JettyInstaller.jetty_app_configuration

        for service in jetty_services:
            service_default_fn = os.path.join(default_dir, service)
            if os.path.exists(service_default_fn):
                usedRatio += jetty_services[service]['memory']['ratio']
                if service == 'jans-auth':
                    service_prop = base.read_properties_file(service_default_fn)
                    m = re.search('-Xmx(\d*)m', service_prop['JAVA_OPTIONS'])
                    oxauth_max_heap_mem = int(m.groups()[0])

        if oxauth_max_heap_mem:
            ratioMultiplier = 1.0 + (1.0 - usedRatio)/usedRatio
            applicationMemory = oxauth_max_heap_mem / jetty_services['jans-auth']['memory']['jvm_heap_ration']
            allowedRatio = jetty_services['jans-auth']['memory']['ratio'] * ratioMultiplier
            application_max_ram = int(round(applicationMemory / allowedRatio))

        Config.os_type = base.os_type
        Config.os_version = base.os_version

        if not Config.get('ip'):
            Config.ip = self.detect_ip()

        Config.installScimServer = os.path.exists(os.path.join(Config.jetty_base, 'jans-scim/start.ini'))
        Config.installFido2 = os.path.exists(os.path.join(Config.jetty_base, 'jans-fido2/start.ini'))
        Config.installEleven = os.path.exists(os.path.join(Config.jetty_base, 'jans-eleven/start.ini'))
        Config.installConfigApi = os.path.exists(os.path.join(Config.jansOptFolder, 'jans-config-api'))

