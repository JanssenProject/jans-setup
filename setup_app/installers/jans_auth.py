import os
import glob
import random
import string
import uuid
import json

from setup_app import paths
from setup_app.utils import base
from setup_app.config import Config
from setup_app.installers.jetty import JettyInstaller
from setup_app.static import AppType, InstallOption

class JansAuthInstaller(JettyInstaller):

    def __init__(self):
        setattr(base.current_app, self.__class__.__name__, self)
        self.service_name = 'jans-auth'
        self.app_type = AppType.SERVICE
        self.install_type = InstallOption.OPTONAL
        self.install_var = 'installOxAuth'
        self.register_progess()

        self.source_files = [
                    (os.path.join(Config.distJansFolder, 'jans-auth.war'), 'https://ox.gluu.org/maven/org/gluu/oxauth-server/%s/oxauth-server-%s.war' % (Config.oxVersion, Config.oxVersion)),
                    (os.path.join(Config.distJansFolder, 'jans-auth-rp.war'), 'https://ox.gluu.org/maven/org/gluu/jans-auth-rp/%s/jans-auth-rp-%s.war' % (Config.oxVersion, Config.oxVersion))
                    ]

        self.templates_folder = os.path.join(Config.templateFolder, self.service_name)
        self.output_folder = os.path.join(Config.outputFolder, self.service_name)

        self.json_scripts = os.path.join(Config.outputFolder, 'scripts.json')
        self.json_config = os.path.join(self.output_folder, 'configuration.json')
        self.json_clients = os.path.join(self.output_folder, 'clients.json')
        self.oxauth_config_json = os.path.join(self.output_folder, 'jans-auth-config.json')
        self.oxauth_static_conf_json = os.path.join(self.templates_folder, 'jans-auth-static-conf.json')
        self.oxauth_error_json = os.path.join(self.templates_folder, 'jans-auth-errors.json')
        self.oxauth_openid_jwks_fn = os.path.join(self.output_folder, 'jans-auth-keys.json')
        self.oxauth_openid_jks_fn = os.path.join(Config.certFolder, 'jans-auth-keys.jks')


    def install(self):
        self.logIt("Copying auth.war into jetty webapps folder...")

        self.installJettyService(self.jetty_app_configuration[self.service_name], True)

        jettyServiceWebapps = os.path.join(self.jetty_base, self.service_name,  'webapps')
        self.copyFile(self.source_files[0][0], jettyServiceWebapps)
        self.enable()

    def generate_configuration(self):
        if not Config.get('oxauth_openid_jks_pass'):
            Config.oxauth_openid_jks_pass = self.getPW()

        if not Config.get('admin_inum'):
            Config.admin_inum = str(uuid.uuid4())

        self.check_clients([('oxauth_client_id', '1001.')])
        
        if not Config.get('oxauthClient_pw'):
            Config.oxauthClient_pw = self.getPW()
            Config.oxauthClient_encoded_pw = self.obscure(Config.oxauthClient_pw)

        self.logIt("Generating OAuth openid keys", pbar=self.service_name)
        sig_keys = 'RS256 RS384 RS512 ES256 ES384 ES512 PS256 PS384 PS512'
        enc_keys = 'RSA1_5 RSA-OAEP'
        jwks = self.gen_openid_jwks_jks_keys(self.oxauth_openid_jks_fn, Config.oxauth_openid_jks_pass, key_expiration=2, key_algs=sig_keys, enc_keys=enc_keys)
        self.write_openid_keys(self.oxauth_openid_jwks_fn, jwks)

    def render_import_templates(self):

        for tmp in (self.oxauth_config_json,):
            self.renderTemplateInOut(tmp, self.templates_folder, self.output_folder)

        Config.templateRenderingDict['oxauth_config'] = json.dumps(self.readFile(self.oxauth_config_json))
        Config.templateRenderingDict['oxauth_static_conf'] = json.dumps(self.readFile(self.oxauth_static_conf_json))
        Config.templateRenderingDict['oxauth_error'] = json.dumps(self.readFile(self.oxauth_error_json))
        Config.templateRenderingDict['oxauth_openid_key'] = json.dumps(self.readFile(self.oxauth_openid_jwks_fn))


        self.renderTemplateInOut(self.json_scripts, Config.templateFolder, Config.outputFolder)
        self.renderTemplateInOut(self.json_config, self.templates_folder, self.output_folder)
        self.renderTemplateInOut(self.json_clients, self.templates_folder, self.output_folder)

        self.dbUtils.import_templates([self.json_config, self.json_clients, self.json_scripts])


    def install_oxauth_rp(self):
        self.download_files(downloads=[self.source_files[1][0]])

        Config.pbar.progress(self.service_name, "Installing OxAuthRP", False)

        self.logIt("Copying jans-auth-rp.war into jetty webapps folder...")

        jettyServiceName = 'jans-auth-rp'
        self.installJettyService(self.jetty_app_configuration[jettyServiceName])

        jettyServiceWebapps = os.path.join(self.jetty_base, jettyServiceName, 'webapps')
        self.copyFile(self.source_files[1][0], jettyServiceWebapps)

        self.enable('jans-auth-rp')

    def genRandomString(self, N):
        return ''.join(random.SystemRandom().choice(string.ascii_lowercase
                                                    + string.ascii_uppercase
                                                    + string.digits) for _ in range(N))
    def make_salt(self, enforce=False):
        if not Config.get('pairwiseCalculationKey') or enforce:
            Config.pairwiseCalculationKey = self.genRandomString(random.randint(20,30))
        if not Config.get('pairwiseCalculationSalt') or enforce:
            Config.pairwiseCalculationSalt = self.genRandomString(random.randint(20,30))

    def copy_static(self):
        self.copyFile(
                os.path.join(Config.install_dir, 'static/auth/lib/duo_web.py'),
                os.path.join(Config.jansOptPythonFolder, 'libs' )
            )
        
        for conf_fn in ('duo_creds.json', 'gplus_client_secrets.json', 'super_gluu_creds.json',
                        'vericloud_jans_creds.json', 'cert_creds.json', 'otp_configuration.json'):
            
            src_fn = os.path.join(Config.install_dir, 'static/auth/conf', conf_fn)
            self.copyFile(src_fn, Config.certFolder)
    
    def installed(self):
        return os.path.exists(os.path.join(Config.jetty_base, self.service_name, 'start.ini'))
