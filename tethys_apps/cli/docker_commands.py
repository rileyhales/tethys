"""
********************************************************************************
* Name: docker_commands.py
* Author: Nathan Swain
* Created On: July 2014
* Copyright: (c) Brigham Young University 2014
* License: BSD 2-Clause
********************************************************************************
"""

import subprocess
from subprocess import PIPE
import os
import sys
import json
import getpass
from exceptions import OSError
from functools import cmp_to_key
from docker.utils import kwargs_from_env, compare_version
from docker.client import Client as DockerClient
from docker.constants import DEFAULT_DOCKER_API_VERSION as MAX_CLIENT_DOCKER_API_VERSION


__all__ = ['docker_init', 'docker_start',
           'docker_stop', 'docker_status',
           'docker_update', 'docker_remove',
           'docker_ip', 'docker_restart',
           'POSTGIS_INPUT', 'GEOSERVER_INPUT', 'N52WPS_INPUT']

MINIMUM_API_VERSION = '1.12'

OSX = 1
WINDOWS = 2
LINUX = 3

POSTGIS_IMAGE = 'ciwater/postgis:2.1.2'
GEOSERVER_IMAGE = 'ciwater/geoserver:2.8.2-clustered'
N52WPS_IMAGE = 'ciwater/n52wps:3.3.1'

REQUIRED_DOCKER_IMAGES = [POSTGIS_IMAGE,
                          GEOSERVER_IMAGE,
                          N52WPS_IMAGE]

POSTGIS_CONTAINER = 'tethys_postgis'
GEOSERVER_CONTAINER = 'tethys_geoserver'
N52WPS_CONTAINER = 'tethys_wps'

POSTGIS_INPUT = 'postgis'
GEOSERVER_INPUT = 'geoserver'
N52WPS_INPUT = 'wps'

ALL_DOCKER_INPUTS = (POSTGIS_INPUT, GEOSERVER_INPUT, N52WPS_INPUT)

DEFAULT_POSTGIS_PORT = '5435'
DEFAULT_GEOSERVER_PORT = '8181'
DEFAULT_N52WPS_PORT = '8282'

REQUIRED_DOCKER_CONTAINERS = [POSTGIS_CONTAINER,
                              GEOSERVER_CONTAINER,
                              N52WPS_CONTAINER]

DEFAULT_DOCKER_HOST = '127.0.0.1'


def validate_numeric_cli_input(value, default, max=None):
    if value == '':
        return str(default)

    valid = False
    while not valid:
        try:
            float(value)
        except ValueError:
            raw_input('Not a valid value, please enter a number: ')
            valid = False
            continue

        if float(value) > max:
            raw_input('Value must be less than {0}: '.format(max))
        else:
            valid = True
    return value


def get_api_version(*versions):
    """
    Find the right version of the client to use.
    credits: @kevinastone https://github.com/docker/docker-py/issues/439
    """
    # compare_version is backwards
    def cmp(a, b):
        return -1 * compare_version(a, b)
    return min(versions, key=cmp_to_key(cmp))


def get_docker_client():
    """
    Try to fire up boot2docker and set any environmental variables
    """
    # For Mac
    try:
        # Get boot2docker info (will fail if not Mac)
        process = ['boot2docker', 'info']
        p = subprocess.Popen(process, stdout=PIPE)
        boot2docker_info = json.loads(p.communicate()[0])

        # Defaults
        docker_host = ''
        docker_cert_path = ''
        docker_tls_verify = ''

        # Start the boot2docker VM if it is not already running
        if boot2docker_info['State'] != "running":
            print('Starting Boot2Docker VM:')
            # Start up the Docker VM
            process = ['boot2docker', 'start']
            subprocess.call(process)

        if ('DOCKER_HOST' not in os.environ) or ('DOCKER_CERT_PATH' not in os.environ) or ('DOCKER_TLS_VERIFY' not in os.environ):
            # Get environmental variable values
            process = ['boot2docker', 'shellinit']
            p = subprocess.Popen(process, stdout=PIPE)
            boot2docker_envs = p.communicate()[0].split()

            for env in boot2docker_envs:
                if 'DOCKER_HOST' in env:
                    docker_host = env.split('=')[1]
                elif 'DOCKER_CERT_PATH' in env:
                    docker_cert_path = env.split('=')[1]
                elif 'DOCKER_TLS_VERIFY' in env:
                    docker_tls_verify = env.split('=')[1]

            # Set environmental variables
            os.environ['DOCKER_TLS_VERIFY'] = docker_tls_verify
            os.environ['DOCKER_HOST'] = docker_host
            os.environ['DOCKER_CERT_PATH'] = docker_cert_path
        else:
            # Handle case when boot2docker is already running
            docker_host = os.environ['DOCKER_HOST'].split('=')[1]

        # Get the arguments form the environment
        client_kwargs = kwargs_from_env(assert_hostname=False)
        client_kwargs['version'] = MINIMUM_API_VERSION

        # Find the right version of the API by creating a DockerClient with the minimum working version
        # Then test to see if the Docker is running a later version than the minimum
        # See: https://github.com/docker/docker-py/issues/439
        version_client = DockerClient(**client_kwargs)
        client_kwargs['version'] = get_api_version(MAX_CLIENT_DOCKER_API_VERSION, version_client.version()['ApiVersion'])

        # Create Real Docker client
        docker_client = DockerClient(**client_kwargs)

        # Derive the host address only from string formatted: "tcp://<host>:<port>"
        docker_client.host = docker_host.split(':')[1].strip('//')

        return docker_client

    # For Linux
    except OSError:
        # Find the right version of the API by creating a DockerClient with the minimum working version
        # Then test to see if the Docker is running a later version than the minimum
        # See: https://github.com/docker/docker-py/issues/439
        version_client = DockerClient(base_url='unix://var/run/docker.sock', version=MINIMUM_API_VERSION)
        version = get_api_version(MAX_CLIENT_DOCKER_API_VERSION, version_client.version()['ApiVersion'])
        docker_client = DockerClient(base_url='unix://var/run/docker.sock', version=version)
        docker_client.host = DEFAULT_DOCKER_HOST

        return docker_client

    except:
        raise


def stop_boot2docker():
    """
    Shut down boot2docker if applicable
    """
    try:
        process = ['boot2docker', 'stop']
        subprocess.call(process)
        print('Boot2Docker VM Stopped')
    except OSError:
        pass

    except:
        raise


def get_images_to_install(docker_client, containers=ALL_DOCKER_INPUTS):
    """
    Get a list of the Docker images that are not already installed/pulled.

    Args:
      docker_client(docker.client.Client): docker-py client.

    Returns:
      (list): A list of the image tags that need to be installed.
    """
    # Get list of images
    images_to_install = []
    for container in containers:
        if container == POSTGIS_INPUT:
            images_to_install.append(POSTGIS_IMAGE)
        elif container == GEOSERVER_INPUT:
            images_to_install.append(GEOSERVER_IMAGE)
        elif container == N52WPS_INPUT:
            images_to_install.append(N52WPS_IMAGE)

    # Search through all the images already installed (pulled) and pop them off the list
    images = docker_client.images()
    for image in images:
        tags = image['RepoTags']

        for image_to_install in images_to_install:
            if image_to_install in tags:
                images_to_install.pop(images_to_install.index(image_to_install))

    return images_to_install


def get_containers_to_create(docker_client, containers=ALL_DOCKER_INPUTS):
    """
    Get a list of containers that need to be created.
    """
    # All assumed to need creating by default
    containers_to_create = []
    for container in containers:
        if container == POSTGIS_INPUT:
            containers_to_create.append(POSTGIS_CONTAINER)
        elif container == GEOSERVER_INPUT:
            containers_to_create.append(GEOSERVER_CONTAINER)
        elif container == N52WPS_INPUT:
            containers_to_create.append(N52WPS_CONTAINER)

    # Create containers for each image if not done already
    containers = docker_client.containers(all=True)

    for c in containers:
        names = c['Names']

        for container_to_create in containers_to_create:
            if '/' + container_to_create in names:
                containers_to_create.pop(containers_to_create.index(container_to_create))

    return containers_to_create


def log_pull_stream(stream):
    """
    Handle the printing of pull statuses
    """
    # Experimental printing
    previous_id = ''
    previous_message = ''

    for line in stream:
        json_line = json.loads(line)
        current_id = json_line['id'] if 'id' in json_line else ''
        current_status = json_line['status'] if 'status' in json_line else ''

        # Update prompt
        backspaces = '\b' * len(previous_message)
        spaces = ' ' * len(previous_message)
        current_message = '\n{0}: {1}'.format(current_id, current_status)

        if current_status == 'Downloading' or current_status == 'Extracting':
            current_message = '{0} {1}'.format(current_message, json_line['progress'])

        # Handle no id case
        if not current_id:
            sys.stdout.write('\n{0}'.format(current_status))

        # Overwrite current line if id is the same
        elif current_id == previous_id:
            sys.stdout.write(backspaces)
            sys.stdout.write(spaces)
            sys.stdout.write(backspaces)
            sys.stdout.write(current_message.strip())

        # Start new line
        else:
            sys.stdout.write(current_message)

        # Flush to out
        sys.stdout.flush()

        # Save state
        previous_message = current_message
        previous_id = current_id
    print()


def get_docker_container_dicts(docker_client):
    # Check status of containers
    containers = docker_client.containers(all=True)
    container_dicts = dict()

    for container in containers:

        if '/' + POSTGIS_CONTAINER in container['Names']:
            container_dicts[POSTGIS_CONTAINER] = container

        elif '/' + GEOSERVER_CONTAINER in container['Names']:
            container_dicts[GEOSERVER_CONTAINER] = container

        elif '/' + N52WPS_CONTAINER in container['Names']:
            container_dicts[N52WPS_CONTAINER] = container

    return container_dicts


def get_docker_container_status(docker_client):
    """
    Returns a dictionary representing the container status. If a container is included in the dictionary keys, it is
    installed. If its key is not included, it means it is not installed. If its value is False, it is not running.
    If its value is True, it is running.
    """
    # Check status of containers
    containers = docker_client.containers()
    all_containers = docker_client.containers(all=True)
    container_status = dict()

    # If in all containers list, assume off (False) until verified in only running containers list
    for container in all_containers:
        if '/' + POSTGIS_CONTAINER in container['Names']:
            container_status[POSTGIS_CONTAINER] = False

        elif '/' + GEOSERVER_CONTAINER in container['Names']:
            container_status[GEOSERVER_CONTAINER] = False

        elif '/' + N52WPS_CONTAINER in container['Names']:
            container_status[N52WPS_CONTAINER] = False

    # Verify running containers
    for container in containers:

        if '/' + POSTGIS_CONTAINER in container['Names']:
            container_status[POSTGIS_CONTAINER] = True

        elif '/' + GEOSERVER_CONTAINER in container['Names']:
            container_status[GEOSERVER_CONTAINER] = True

        elif '/' + N52WPS_CONTAINER in container['Names']:
            container_status[N52WPS_CONTAINER] = True

    return container_status


def install_docker_containers(docker_client, force=False, containers=ALL_DOCKER_INPUTS, defaults=False):
    """
    Install all Docker containers
    """
    # Check for containers that need to be created
    containers_to_create = get_containers_to_create(docker_client, containers=containers)

    # PostGIS
    if POSTGIS_CONTAINER in containers_to_create or force:
        print("\nInstalling the PostGIS Docker container...")

        # Default environmental vars
        tethys_default_pass = 'pass'
        tethys_db_manager_pass = 'pass'
        tethys_super_pass = 'pass'

        # User environmental variables
        if not defaults:
            print("Provide passwords for the three Tethys database users or press enter to accept the default "
                  "passwords shown in square brackets:")

            # tethys_default
            tethys_default_pass_1 = getpass.getpass('Password for "tethys_default" database user [pass]: ')

            if tethys_default_pass_1 != '':
                tethys_default_pass_2 = getpass.getpass('Confirm password for "tethys_default" database user: ')

                while tethys_default_pass_1 != tethys_default_pass_2:
                    print('Passwords do not match, please try again: ')
                    tethys_default_pass_1 = getpass.getpass('Password for "tethys_default" database user [pass]: ')
                    tethys_default_pass_2 = getpass.getpass('Confirm password for "tethys_default" database user: ')

                tethys_default_pass = tethys_default_pass_1
            else:
                tethys_default_pass = 'pass'

            # tethys_db_manager
            tethys_db_manager_pass_1 = getpass.getpass('Password for "tethys_db_manager" database user [pass]: ')

            if tethys_db_manager_pass_1 != '':
                tethys_db_manager_pass_2 = getpass.getpass('Confirm password for "tethys_db_manager" database user: ')

                while tethys_db_manager_pass_1 != tethys_db_manager_pass_2:
                    print('Passwords do not match, please try again: ')
                    tethys_db_manager_pass_1 = getpass.getpass('Password for "tethys_db_manager" database user [pass]: ')
                    tethys_db_manager_pass_2 = getpass.getpass('Confirm password for "tethys_db_manager" database user: ')

                tethys_db_manager_pass = tethys_db_manager_pass_1
            else:
                tethys_db_manager_pass = 'pass'

            # tethys_super
            tethys_super_pass_1 = getpass.getpass('Password for "tethys_super" database user [pass]: ')

            if tethys_super_pass_1 != '':
                tethys_super_pass_2 = getpass.getpass('Confirm password for "tethys_super" database user: ')

                while tethys_super_pass_1 != tethys_super_pass_2:
                    print('Passwords do not match, please try again: ')
                    tethys_super_pass_1 = getpass.getpass('Password for "tethys_super" database user [pass]: ')
                    tethys_super_pass_2 = getpass.getpass('Confirm password for "tethys_super" database user: ')

                tethys_super_pass = tethys_super_pass_1
            else:
                tethys_super_pass = 'pass'

        docker_client.create_container(
            name=POSTGIS_CONTAINER,
            image=POSTGIS_IMAGE,
            environment={'TETHYS_DEFAULT_PASS': tethys_default_pass,
                         'TETHYS_DB_MANAGER_PASS': tethys_db_manager_pass,
                         'TETHYS_SUPER_PASS': tethys_super_pass}
        )

    else:
        print("PostGIS Docker container already installed: skipping.")

    # GeoServer
    if GEOSERVER_CONTAINER in containers_to_create or force:
        print("\nInstalling the GeoServer Docker container...")

        if "cluster" in GEOSERVER_IMAGE:
            # Cluster settings
            enabled_nodes = '1'
            rest_nodes = '1'

            # Flow Control Settings
            max_timeout = '60'
            num_cores = '4'

            max_ows_global = '100'
            max_wms_getmap = '8'
            max_ows_gwc = '16'
            max_per_user = '8'

            if not defaults:
                print("The GeoServer docker can be configured to run in a clustered mode for better performance. This is "
                      "especially useful for production use of GeoServer.")

                enabled_nodes = raw_input('Number of GeoServer Instances Enabled (max 4) [1]: ')
                enabled_nodes = validate_numeric_cli_input(enabled_nodes, 1, 4)

                rest_nodes = raw_input('Number of GeoServer Instances with REST API Enabled (max 4) [1]: ')
                rest_nodes = validate_numeric_cli_input(rest_nodes, 1, 4)

                print("GeoServer can be configured to flow control limits to prevent it from becoming "
                      "overwhelmed with too many simultaneous calls. This can be done automatically based on the "
                      "number of processors the GeoServer is running on or each limit can be set explicitly.")

                flow_control_mode = raw_input('Would you like to specify number of Processors (c) OR set '
                                              'limits explicitly (e): ')
                while flow_control_mode not in ['c' or 'e']:
                    flow_control_mode = raw_input('Invalid option supplied, please enter either "c" to specify number '
                                                  'of cores or "e" to set limits explicitly: ')

                if flow_control_mode == 'c':
                    num_cores = raw_input('Number of Processors [4]: ')
                    if num_cores == '':
                        num_cores = '4'
                else:
                   max_ows_global = raw_input('Maximum Number of Simultaneous OWS Requests [100]: ')
                   max_ows_global = validate_numeric_cli_input(max_ows_global, '100')

                   max_wms_getmap = raw_input('Maximum Number of Simultaneous GetMap Requests [8]: ')
                   max_wms_getmap = validate_numeric_cli_input(max_wms_getmap, '8')

                   max_ows_gwc = raw_input('Maximum Number of Simultaneous GeoWebCache Tile Renders [16]: ')
                   max_ows_gwc = validate_numeric_cli_input(max_ows_gwc, '16')

                   max_per_user = raw_input('Maximum Number of Requests per User [8]: ')
                   max_per_user = validate_numeric_cli_input(max_per_user, '8')


            exit(0)
            docker_client.create_container(
                name=GEOSERVER_CONTAINER,
                image=GEOSERVER_IMAGE
            )
        else:
            exit(0)
            docker_client.create_container(
                name=GEOSERVER_CONTAINER,
                image=GEOSERVER_IMAGE
            )
    else:
        print("GeoServer Docker container already installed: skipping.")

    # 52 North WPS
    if N52WPS_CONTAINER in containers_to_create or force:
        print("\nInstalling the 52 North WPS Docker container...")

        # Default environmental vars
        name = 'NONE'
        position = 'NONE'
        address = 'NONE'
        city = 'NONE'
        state = 'NONE'
        country = 'NONE'
        postal_code = 'NONE'
        email = 'NONE'
        phone = 'NONE'
        fax = 'NONE'
        username = 'wps'
        password = 'wps'

        if not defaults:
            print("Provide contact information for the 52 North Web Processing Service or press enter to accept the "
                  "defaults shown in square brackets: ")

            name = raw_input('Name [NONE]: ')
            if name == '':
                name = 'NONE'

            position = raw_input('Position [NONE]: ')
            if position == '':
                position = 'NONE'

            address = raw_input('Address [NONE]: ')
            if address == '':
                address = 'NONE'

            city = raw_input('City [NONE]: ')
            if city == '':
                city = 'NONE'

            state = raw_input('State [NONE]: ')
            if state == '':
                state = 'NONE'

            country = raw_input('Country [NONE]: ')
            if country == '':
                country = 'NONE'

            postal_code = raw_input('Postal Code [NONE]: ')
            if postal_code == '':
                postal_code = 'NONE'

            email = raw_input('Email [NONE]: ')
            if email == '':
                email = 'NONE'

            phone = raw_input('Phone [NONE]: ')
            if phone == '':
                phone = 'NONE'

            fax = raw_input('Fax [NONE]: ')
            if fax == '':
                fax = 'NONE'

            username = raw_input('Admin Username [wps]: ')

            if username == '':
                username = 'wps'

            password_1 = getpass.getpass('Admin Password [wps]: ')

            if password_1 == '':
                password = 'wps'

            else:
                password_2 = getpass.getpass('Confirm Password: ')

                while password_1 != password_2:
                    print('Passwords do not match, please try again.')
                    password_1 = getpass.getpass('Admin Password [wps]: ')
                    password_2 = getpass.getpass('Confirm Password: ')

                password = password_1

        docker_client.create_container(
            name=N52WPS_CONTAINER,
            image=N52WPS_IMAGE,
            environment={'NAME': name,
                         'POSITION': position,
                         'ADDRESS': address,
                         'CITY': city,
                         'STATE': state,
                         'COUNTRY': country,
                         'POSTAL_CODE': postal_code,
                         'EMAIL': email,
                         'PHONE': phone,
                         'FAX': fax,
                         'USERNAME': username,
                         'PASSWORD': password}
        )

    else:
        print("52 North WPS Docker container already installed: skipping.")

    print("\nThe Docker containers have been successfully installed.")


def container_check(docker_client, containers=ALL_DOCKER_INPUTS):
    """
    Check to ensure containers are installed.
    """
    # Perform this check to make sure the "tethys docker init" command has been run
    containers_needing_to_be_installed = get_containers_to_create(docker_client, containers=containers)

    # if len(containers_needing_to_be_installed) > 0:
    #     print('The following Docker containers have not been installed: {0}'.format(
    #         ', '.join(containers_needing_to_be_installed)))
    #     print('Run the "tethys docker init" command to install them or specify a specific container '
    #           'using the "-c" option.')
    #     exit(1)


def start_docker_containers(docker_client, containers=ALL_DOCKER_INPUTS):
    """
    Start Docker containers
    """
    for container in containers:
        # Get container dicts
        container_status = get_docker_container_status(docker_client)

        # Start PostGIS
        try:
            if not container_status[POSTGIS_CONTAINER] and container == POSTGIS_INPUT:
                print('Starting PostGIS container...')
                docker_client.start(container=POSTGIS_CONTAINER,
                                    restart_policy='always',
                                    port_bindings={5432: DEFAULT_POSTGIS_PORT})
            elif container == POSTGIS_INPUT:
                print('PostGIS container already running...')
        except KeyError:
            if container == POSTGIS_INPUT:
                print('PostGIS container not installed...')
        except:
            raise

        try:
            if not container_status[GEOSERVER_CONTAINER] and container == GEOSERVER_INPUT:
                # Start GeoServer
                print('Starting GeoServer container...')
                docker_client.start(container=GEOSERVER_CONTAINER,
                                    restart_policy='always',
                                    port_bindings={8080: DEFAULT_GEOSERVER_PORT})
            elif not container or container == GEOSERVER_INPUT:
                print('GeoServer container already running...')
        except KeyError:
            if container == GEOSERVER_INPUT:
                print('GeoServer container not installed...')
        except:
            raise

        try:
            if not container_status[N52WPS_CONTAINER] and container == N52WPS_INPUT:
                # Start 52 North WPS
                print('Starting 52 North WPS container...')
                docker_client.start(container=N52WPS_CONTAINER,
                                    restart_policy='always',
                                    port_bindings={8080: DEFAULT_N52WPS_PORT})
            elif container == N52WPS_INPUT:
                print('52 North WPS container already running...')
        except KeyError:
            if not container or container == N52WPS_INPUT:
                print('52 North WPS container not installed...')
        except:
            raise


def stop_docker_containers(docker_client, silent=False, containers=ALL_DOCKER_INPUTS):
    """
    Stop Docker containers
    """
    for container in containers:
        # Get container dicts
        container_status = get_docker_container_status(docker_client)

        # Stop PostGIS
        try:
            if container_status[POSTGIS_CONTAINER] and container == POSTGIS_INPUT:
                if not silent:
                    print('Stopping PostGIS container...')

                docker_client.stop(container=POSTGIS_CONTAINER)

            elif not silent and container == POSTGIS_INPUT:
                print('PostGIS container already stopped.')
        except KeyError:
            if not container or container == POSTGIS_INPUT:
                print('PostGIS container not installed...')
        except:
            raise

        # Stop GeoServer
        try:
            if container_status[GEOSERVER_CONTAINER] and container == GEOSERVER_INPUT:
                if not silent:
                    print('Stopping GeoServer container...')

                docker_client.stop(container=GEOSERVER_CONTAINER)

            elif not silent and container == GEOSERVER_INPUT:
                print('GeoServer container already stopped.')
        except KeyError:
            if not container or container == GEOSERVER_INPUT:
                print('GeoServer container not installed...')
        except:
            raise

        # Stop 52 North WPS
        try:
            if container_status[N52WPS_CONTAINER] and container == N52WPS_INPUT:
                if not silent:
                    print('Stopping 52 North WPS container...')

                docker_client.stop(container=N52WPS_CONTAINER)

            elif not silent and container == N52WPS_INPUT:
                print('52 North WPS container already stopped.')
        except KeyError:
            if not container or container == N52WPS_INPUT:
                print('52 North WPS container not installed...')
        except:
            raise


def remove_docker_containers(docker_client, containers=ALL_DOCKER_INPUTS):
    """
    Remove all docker containers
    """
    # Perform check
    container_check(docker_client, containers=containers)

    for container in containers:
        # Remove PostGIS
        if container == POSTGIS_INPUT:
            print('Removing PostGIS...')
            docker_client.remove_container(container=POSTGIS_CONTAINER)

        # Remove GeoServer
        if container == GEOSERVER_INPUT:
            print('Removing GeoServer...')
            docker_client.remove_container(container=GEOSERVER_CONTAINER)

        # Remove 52 North WPS
        if container == N52WPS_INPUT:
            print('Removing 52 North WPS...')
            docker_client.remove_container(container=N52WPS_CONTAINER)


def docker_init(containers=None, defaults=False):
    """
    Pull Docker images for Tethys Platform and create containers with interactive input.
    """
    # Retrieve a Docker client
    docker_client = get_docker_client()
    containers = ALL_DOCKER_INPUTS if containers is None else containers

    # Check for the correct images
    images_to_install = get_images_to_install(docker_client, containers=containers)

    if len(images_to_install) < 1:
        print("Docker images already pulled.")
    else:
        print("Pulling Docker images...")

    # Pull the Docker images
    for image in images_to_install:
        pull_stream = docker_client.pull(image, stream=True)
        log_pull_stream(pull_stream)

    # Install docker containers
    install_docker_containers(docker_client, containers=containers, defaults=defaults)


def docker_start(containers):
    """
    Start the docker containers
    """
    # Retrieve a Docker client
    docker_client = get_docker_client()
    containers = ALL_DOCKER_INPUTS if containers is None else containers

    # Start the Docker containers
    start_docker_containers(docker_client, containers=containers)


def docker_stop(containers=None, boot2docker=False):
    """
    Stop Docker containers
    """
    # Retrieve a Docker client
    docker_client = get_docker_client()
    containers = ALL_DOCKER_INPUTS if containers is None else containers

    # Stop the Docker containers
    stop_docker_containers(docker_client, containers=containers)

    # Shutdown boot2docker if applicable
    if boot2docker and not containers:
        stop_boot2docker()


def docker_restart(containers=None):
    """
    Restart Docker containers
    """
    # Retrieve a Docker client
    docker_client = get_docker_client()
    containers = ALL_DOCKER_INPUTS if containers is None else containers

    # Stop the Docker containers
    stop_docker_containers(docker_client, containers=containers)

    # Start the Docker containers
    start_docker_containers(docker_client, containers=containers)


def docker_remove(containers=None):
    """
    Remove Docker containers.
    """
    # Retrieve a Docker client
    docker_client = get_docker_client()
    containers = ALL_DOCKER_INPUTS if containers is None else containers

    # Stop the Docker containers
    stop_docker_containers(docker_client, containers=containers)

    # Remove Docker containers
    remove_docker_containers(docker_client, containers=containers)


def docker_status():
    """
    Returns the status of the Docker containers: either Running or Stopped.
    """
    # Retrieve a Docker client
    docker_client = get_docker_client()

    # Get container dicts
    container_status = get_docker_container_status(docker_client)

    # PostGIS
    if POSTGIS_CONTAINER in container_status and container_status[POSTGIS_CONTAINER]:
        print('PostGIS/Database: Running')
    elif POSTGIS_CONTAINER in container_status and not container_status[POSTGIS_CONTAINER]:
        print('PostGIS/Database: Stopped')
    else:
        print('PostGIS/Database: Not Installed')

    # GeoServer
    if GEOSERVER_CONTAINER in container_status and container_status[GEOSERVER_CONTAINER]:
        print('GeoServer: Running')
    elif GEOSERVER_CONTAINER in container_status and not container_status[GEOSERVER_CONTAINER]:
        print('GeoServer: Stopped')
    else:
        print('GeoServer: Not Installed')

    # 52 North WPS
    if N52WPS_CONTAINER in container_status and container_status[N52WPS_CONTAINER]:
        print('52 North WPS: Running')
    elif N52WPS_CONTAINER in container_status and not container_status[N52WPS_CONTAINER]:
        print('52 North WPS: Stopped')
    else:
        print('52 North WPS: Not Installed')


def docker_update(containers=None, defaults=False):
    """
    Remove Docker containers and pull the latest images updates.
    """
    # Retrieve a Docker client
    docker_client = get_docker_client()
    containers = ALL_DOCKER_INPUTS if containers is None else containers

    # Stop containers
    stop_docker_containers(docker_client, containers=containers)

    # Remove containers
    remove_docker_containers(docker_client, containers=containers)

    # Force pull all the images without check to get latest version
    for container in containers:
        if not container:
            required_docker_images = REQUIRED_DOCKER_IMAGES
        elif container == POSTGIS_INPUT:
            required_docker_images = [POSTGIS_IMAGE]
        elif container == GEOSERVER_INPUT:
            required_docker_images = [GEOSERVER_IMAGE]
        elif container == N52WPS_INPUT:
            required_docker_images = [N52WPS_IMAGE]
        else:
            required_docker_images = []

        for image in required_docker_images:
            pull_stream = docker_client.pull(image, stream=True)
            log_pull_stream(pull_stream)

    # Reinstall containers
    install_docker_containers(docker_client, force=True, containers=containers, defaults=defaults)


def docker_ip():
    """
    Returns the hosts and ports of the Docker containers.
    """
    # Retrieve a Docker client
    docker_client = get_docker_client()

    # Containers
    containers = get_docker_container_dicts(docker_client)
    container_status = get_docker_container_status(docker_client)
    docker_host = docker_client.host

    # PostGIS
    try:
        if container_status[POSTGIS_CONTAINER]:
            postgis_container = containers[POSTGIS_CONTAINER]
            postgis_port = postgis_container['Ports'][0]['PublicPort']
            print('\nPostGIS/Database:')
            print('  Host: {0}'.format(docker_host))
            print('  Port: {0}'.format(postgis_port))

        else:
            print('\nPostGIS/Database: Not Running.')
    except KeyError:
        # If key error is raised, it is likely not installed.
        print('\nPostGIS/Database: Not Installed.')
    except:
        raise

    # GeoServer
    try:
        if container_status[GEOSERVER_CONTAINER]:
            geoserver_container = containers[GEOSERVER_CONTAINER]
            geoserver_port = geoserver_container['Ports'][0]['PublicPort']
            print('\nGeoServer:')
            print('  Host: {0}'.format(docker_host))
            print('  Port: {0}'.format(geoserver_port))
            print('  Endpoint: http://{0}:{1}/geoserver/rest'.format(docker_host, geoserver_port))

        else:
            print('\nGeoServer: Not Running.')
    except KeyError:
        # If key error is raised, it is likely not installed.
        print('\nGeoServer: Not Installed.')
    except:
        raise

    # 52 North WPS
    try:
        if container_status[N52WPS_CONTAINER]:
            n52wps_container = containers[N52WPS_CONTAINER]
            n52wps_port = n52wps_container['Ports'][0]['PublicPort']
            print('\n52 North WPS:')
            print('  Host: {0}'.format(docker_host))
            print('  Port: {0}'.format(n52wps_port))
            print('  Endpoint: http://{0}:{1}/wps/WebProcessingService\n'.format(docker_host, n52wps_port))

        else:
            print('\n52 North WPS: Not Running.')
    except KeyError:
        # If key error is raised, it is likely not installed.
        print('\n52 North WPS: Not Installed.')
    except:
        raise
