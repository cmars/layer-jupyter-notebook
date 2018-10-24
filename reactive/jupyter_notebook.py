import os
import subprocess

from charmhelpers.core import hookenv, host, templating, unitdata
from charmhelpers.core.host import chownr
from charms.reactive import endpoint_from_flag, when, when_not, set_flag, clear_flag

JUPYTER_DIR = '/opt/jupyter'
PIP_PACKAGES = ['jupyter', 'matplotlib', 'numpy', 'pandas',
                'scipy', 'scikit-learn', 'requests']


@when_not('notebook.installed')
def install_notebook_dep():
    subprocess.call(['pip3', 'install', '--upgrade', 'notebook'])
    set_flag('notebook.installed')


@when_not('jupyter-notebook.config.dir.available')
def create_jupyter_config_dir():
    os.makedirs(JUPYTER_DIR, exist_ok=True)
    chownr(JUPYTER_DIR, 'ubuntu', 'ubuntu', chowntopdir=True)
    set_flag('jupyter-notebook.config.dir.available')


@when_not('jupyter-notebook.installed')
def install_jupyter_notebook():
    hookenv.log("Installing Jupyter-notebook and pip packages")

    conf = hookenv.config()

    if conf.get('http-proxy'):
        os.putenv('http_proxy', conf['http-proxy'])
        os.environ['http_proxy'] = conf['http-proxy']
    if conf.get('https-proxy'):
        os.putenv('https_proxy', conf['https-proxy'])
        os.environ['https_proxy'] = conf['https-proxy']

    extra_pip_packages = conf.get('extra-pip-packages').split()
    subprocess.call(['pip3', 'install', '--upgrade'] +
        PIP_PACKAGES + extra_pip_packages)

    # Set installed flag
    set_flag('jupyter-notebook.installed')


@when('config.changed', 'notebook.installed', 'jupyter-notebook.installed')
def config_changed():
    init_configure_jupyter_notebook()


@when('notebook.installed',
      'jupyter-notebook.installed',
      'jupyter-notebook.config.dir.available')
@when_not('jupyter-notebook.init.config.available')
def init_configure_jupyter_notebook():

    conf = hookenv.config()
    kv = unitdata.kv()

    if conf.get('jupyter-web-password'):
        kv.set('password', conf.get('jupyter-web-password'))
    else:
        kv.set('password', generate_password())

    ctxt = {
        'port': conf.get('jupyter-web-port'),
        'password_hash': generate_hash(kv.get('password')),
        'base_url': conf.get('jupyter-base-url'),
    }

    templating.render(
        source='jupyter_notebook_config.py.j2',
        target=os.path.join(JUPYTER_DIR, 'jupyter_notebook_config.py'),
        context=ctxt,
        owner='ubuntu',
        group='ubuntu',
    )
    set_flag('jupyter-notebook.init.config.available')


@when('jupyter-notebook.init.config.available')
@when_not('jupyter-notebook.systemd.available')
def render_systemd():
    render_jupyter_systemd_template()
    set_flag('jupyter-notebook.systemd.available')


@when('jupyter-notebook.systemd.available')
@when_not('jupyter-notebook.init.available')
def jupyter_init_available():
    conf = hookenv.config()
    restart_notebook()
    if host.service_running('jupyter-notebook'):
        hookenv.open_port(conf.get('jupyter-web-port'))
        set_flag('jupyter-notebook.init.available')
    else:
        hookenv.status_set('blocked', "Jupyter could not start - Please DEBUG")


@when('conda.available')
@when_not('conda.relation.data.available')
def set_conda_relation_data():
    """Set conda endpoint relation data
    """
    conf = hookenv.config()
    endpoint = endpoint_from_flag('conda.available')

    ctxt = {'url': conf.get('conda-installer-url'),
            'sha': conf.get('conda-installer-sha256')}

    if conf.get('conda-extra-packages'):
        ctxt['conda_extra_packages'] = conf.get('conda-extra-packages')

    if conf.get('conda-extra-pip-packages'):
        ctxt['conda_extra_pip_packages'] = \
            conf.get('conda-extra-pip-packages')

    endpoint.configure(**ctxt)
    set_flag('conda.relation.data.available')
    clear_flag('conda.available')


@when('http.available',
      'jupyter-notebook.init.available')
def configure_http():
    conf = hookenv.config()
    endpoint = endpoint_from_flag('http.available')
    endpoint.configure(port=conf.get('jupyter-web-port'))
    clear_flag('http.available')


def restart_notebook():
    if host.service_running('jupyter-notebook'):
        host.service_stop('jupyter-notebook')
        import time
        time.sleep(10)
    # service_resume also enables the serivice on startup
    host.service_resume('jupyter-notebook')
    jupyter_status()


def jupyter_status():
    if host.service_running('jupyter-notebook'):
        hookenv.status_set(
            'active',
            'Ready (Pass: "{}")'.format(unitdata.kv().get('password'))
        )
    else:
        hookenv.status_set(
            'blocked',
            'Could not restart service due to wrong configuration!'
        )


def render_jupyter_systemd_template(ctxt=None):
    """Render Jupyter Systemd template
    """

    if not ctxt:
        ctxt = {}

    ctxt['jupyter_bin'] = '/usr/local/bin/jupyter'

    templating.render(
        source='jupyter-notebook.service.j2',
        target='/etc/systemd/system/jupyter-notebook.service',
        context=ctxt,
    )
    subprocess.check_call(['systemctl', 'daemon-reload'])


def generate_hash(password):
    from notebook.auth import passwd
    return passwd(password)


def generate_password():
    from xkcdpass import xkcd_password as xp
    mywords = xp.generate_wordlist()
    return xp.generate_xkcdpassword(mywords, numwords=4)
