# TODO: delete ports from URLs


#!/usr/bin/python
from datetime import datetime, timedelta
import re
import time
from urllib.parse import parse_qsl, urlparse, parse_qs
from urllib3.exceptions import InsecureRequestWarning
from requests.auth import HTTPBasicAuth
import requests
import urllib
import usock
import os
import pathlib
import paho.mqtt.client as mqtt
import json
import threading
import warnings



#---------------------#
# Socket settings
usock.sockAddr = "/var/lib/waziapp/proxy.sock"      # Production mode
#usock.sockAddr = "proxy.sock"                      # Debug mode

# URL of API to retrive devices
DeviceApiUrl = "http://wazigate/devices/"           # Production mode
#DeviceApiUrl = "http://localhost:8080/devices/"    # Debug mode
#DeviceApiUrl = "http://192.168.188.29/devices/"    # Debug mode

# Path to the root of the code
PATH = os.path.dirname(os.path.abspath(__file__))

# global list of device and sensor ids
DeviceAndSensorIdsSync = []

# Url to post data
Target_url = ""

# ID
Id = "123"

# GPS
Gps_info = ""

# Threshold in sec to obtain related values from API
Threshold = 1

# Array of active threads
Threads = []
ThreadId = 0 

# Already synced devices
SyncedDevices = []

Auth = "basic"

# Saved config
ConfigPath = "/var/lib/waziapp/config.json"     # Production
#ConfigPath = "config.json"                      # Debug mode


#---------------------#


def index(url, body=""):
    return 200, b"Salam Goloooo", []


usock.routerGET("/", index)

#------------------#


def ui(url, body=''):
    filename = urlparse(url).path.replace("/ui/", "")
    if (len(filename) == 0):
        filename = 'index.html'

    #---------------#

    ext = pathlib.Path(filename).suffix

    extMap = {
        '': 'application/octet-stream',
        '.manifest': 'text/cache-manifest',
        '.html': 'text/html',
        '.png': 'image/png',
        '.jpg': 'image/jpg',
        '.svg':	'image/svg+xml',
        '.css':	'text/css',
        '.js': 'application/x-javascript',
        '.wasm': 'application/wasm',
        '.json': 'application/json',
        '.xml': 'application/xml',
    }

    if ext not in extMap:
        ext = ""

    conType = extMap[ext]

    #---------------#

    try:
        with open(PATH + '/ui/' + filename, mode='rb') as file:
            return 200, file.read(), [conType]
    except Exception as e:
        print("Error: ", e)
        return 404, b"File not found", []


usock.routerGET("/ui/(.*)", ui)
usock.routerPOST("/ui/(.*)", ui)

#------------------#


# Save config to reload configuration -> only important for sync future values
def saveConfig(usr, passw):
    # Organize the variables into a dictionary
    data = {
        "DeviceAndSensorIdsSync": DeviceAndSensorIdsSync,
        "Target_url": Target_url,
        "Id": Id,
        "Gps_info": {"lattitude": Gps_info.split(',')[0].lstrip(), "longitude": Gps_info.split(',')[1].lstrip()},
        "Threshold": Threshold,
        "usr": usr,
        "passw": passw,
        "auth": Auth
    }

    # Save the JSON data to the file
    with open(ConfigPath, 'w') as json_file:
        json.dump(data, json_file, indent=4)

# Resume operation after restart from data saved in config file
def resumeAfterRestart():
    global ThreadId
    global DeviceAndSensorIdsSync
    global Target_url
    global Id
    global Gps_info
    global Threshold
    global Auth
    global Threads

    if os.path.isfile(ConfigPath): 
        print("Found existing config file, load config and sync again!")
        
        # Load data from file
        with open(ConfigPath, 'r') as file:
            # Parse JSON from the file
            data = json.load(file)

        # Get choosen sensors
        DeviceAndSensorIdsSync = data.get('DeviceAndSensorIdsSync', [])

        # Get data from forms
        Target_url = data.get('Target_url', [])
        Id = data.get('Id', [])
        # as string needed
        Gps_info = data.get('Gps_info', [])
        Gps_info = Gps_info["lattitude"] + ", " + Gps_info["longitude"]
        Threshold = int(data.get('Threshold', []))
        usr = data.get('usr', [])
        passw = data.get('passw', [])
        Auth = data.get('auth', [])

        # Start sync         
        thread = WorkerThread(DeviceAndSensorIdsSync, usr, passw)

        # Append thread to list
        Threads.append(thread)

        # Start the thread
        thread.start()
    else:
        msg = "Found no existing config file, cannot continue sync."
        print(msg)

# Fill forms of html page with existing config
def getConfig(url, body):
    global DeviceAndSensorIdsSync
    global Target_url
    global Id
    global Gps_info
    global Threshold

    if os.path.isfile(ConfigPath): 
        print("Found existing config file, load config and display it again!")
        
        # Load data from file
        with open(ConfigPath, 'r') as file:
            # Parse JSON from the file
            data = json.load(file)    

        # send to frontend to fill forms of html page with existing config
        return 200, bytes(json.dumps(data), "utf8"), []
    else:
        response_data = {"config": False}
        status_code = 404

        return status_code, bytes(json.dumps(response_data), "utf8"), []
    
usock.routerGET("/api/getConfig", getConfig)


# Helper function to create json for one message and send to endpoint
def postMessageToEndpoint(data, usr, passw):
    # Create a session
    session = requests.Session()

    # Set the auth
    session.auth = HTTPBasicAuth(usr, passw)
    
    # Suppress the InsecureRequestWarning
    session.verify = False  # Disable SSL verification
    warnings.simplefilter('ignore', InsecureRequestWarning)

    # Forward data to the database
    response = session.post(Target_url, json=data, verify=False)

    m = ""
    if response.status_code == 200:
        m = "Data forwarded to the database successfully"
    else:
        m = "Failed to forward data to the database:" + str(response.status_code)
    print(m)
    
    return m
    

# Helper function to create json for multiple messages and send to endpoint
def postMessagesToEndpoint(connected_data, usr, passw):
    # Create a session
    session = requests.Session()

    # Set the auth
    session.auth = HTTPBasicAuth(usr, passw)

    # Suppress the InsecureRequestWarning
    session.verify = False  # Disable SSL verification
    warnings.simplefilter('ignore', InsecureRequestWarning)

    # Iterate through the list and send each dictionary as a JSON POST request
    for dictionary in connected_data:
        # Convert the dictionary to JSON format
        #json_data = json.dumps(dictionary)
        
        # Send a POST request with the JSON data to the database endpoint
        response = session.post(Target_url, json=dictionary, verify=False)
        
        # Check the response status (optional)
        m = ""
        if response.status_code == 200:
            m += "Data forwarded to the database successfully"
        else:
            m += "Failed to forward data to the database:" + str(response.status_code)
    print(m)
    return m

# Helper function to obtain a JWT token
def get_jwt_token(usr, passw):
    # Create user credential payload
    payload = {"username": usr, "password": passw}
    # Create the URL for the authentication endpoint
    auth_url = re.sub(r'(:\d+).*$', r'\1', Target_url) + "/user/getToken"

    # Create a session
    session = requests.Session()    
    # Suppress the InsecureRequestWarning
    session.verify = False  # Disable SSL verification
    warnings.simplefilter('ignore', InsecureRequestWarning)

    # Perform request to obtain token
    response = session.post(auth_url, json=payload, verify=False)

    # Check if the request was successful
    if response.status_code == 200:
        return response.json().get("access_token")  # Adjust if the key is different TODO
    else:
        print(f"Failed to obtain token: {response.status_code}, {response.text}")
        return None

# Helper function to send data using JWT authentication
def post_message_to_endpoint(data, token):
    headers = {"Authorization": f"Bearer {token}"}  # Use Bearer token in the header

    # Create a session
    session = requests.Session()    
    # Suppress the InsecureRequestWarning
    session.verify = False  # Disable SSL verification
    warnings.simplefilter('ignore', InsecureRequestWarning)

    # Forward data to the database endpoint
    response = session.post(Target_url, json=data, headers=headers, verify=False)

    if response.status_code == 200:
        print("Data forwarded successfully")
        return "Data forwarded successfully"
    else:
        print(f"Failed to forward data: {response.status_code}, {response.text}")
        return f"Failed to forward data: {response.status_code}"

# Helper to search other sensor values and 
def getSensorAtTheSameTime(deviceAndSensorIds, dataOfFirstSensor):
    # # Mapping names of sensors to the names to endpoints requirements
    # mapping = {
    #     "time": "timestamp",
    #     "sensorId": "sensorId",
    #     "lon": "longitude",
    #     "lat": "latitude",
    #     "sensor1": "payload_hex"
    # }

    # Dict to return in the end
    allSensorsDict = {
            "sensorId": None,
            "timestamp": None,
            "location": {
                "longitude": None,
                "latitude": None
            },
            "payload_hex": None
    }

    # Get time of first sensor in list
    time = dataOfFirstSensor['time']
    # Set time of the first selected sensor as time of the dict
    allSensorsDict["timestamp"] = time
    # Set given sensor id to dict
    allSensorsDict["sensorId"] = Id
    # Set GPS coordinates
    coordinates = Gps_info.split(",")
    allSensorsDict["location"]["longitude"] = round(float(coordinates[1]), 6)
    allSensorsDict["location"]["latitude"] = round(float(coordinates[0]), 6)
    # Set the payload
    allSensorsDict["payload_hex"] = dataOfFirstSensor["value"] #"000113ec00370010000000000000000000000000" # DEBUG
    # Parse the ISO string into a datetime object
    dateObject = datetime.fromisoformat(time)
    # Subtract and add 5 seconds to get interval
    #fromObject = dateObject - timedelta(seconds=int(Threshold))
    #toObject = dateObject + timedelta(seconds=int(Threshold))

    # # Search all other choosen sensors to see if there are occurances too
    # for sensor in deviceAndSensorIds:
    #     # Create URL for API call
    #     api_url = DeviceApiUrl + sensor.split('/')[0] + "/sensors/" + sensor.split('/')[1] + "/values?from=" + fromObject.isoformat() + "&to=" + toObject.isoformat()
    #     # Parse the URL
    #     parsed_url = urllib.parse.urlsplit(api_url)

    #     # Encode the query parameters
    #     encoded_query = urllib.parse.quote(parsed_url.query, safe='=&')

    #     # Reconstruct the URL with the encoded query
    #     encoded_url = urllib.parse.urlunsplit((parsed_url.scheme, 
    #                                             parsed_url.netloc, 
    #                                             parsed_url.path, 
    #                                             encoded_query, 
    #                                             parsed_url.fragment))
    #     try:
    #         # Send a GET request to the API
    #         response = requests.get(encoded_url)

    #         # Check if the request was successful (status code 200)
    #         if response.status_code == 200:
    #             # The response content contains the data from the API
    #             response_ok = response.json()

    #             # Add values to the all_Sensors_dict
    #             if len(response_ok) != 0:
    #                 try:
    #                     # For sensors that are a related to the Flytrap
    #                     nameToAdd = mapping[sensor.split("/")[1]]
    #                     allSensorsDict[nameToAdd] = round(response_ok[0]["value"], 1)
    #                 except: 
    #                     # For sensor devices that are not a Flytrap 
    #                     nameToAdd = sensor.split("/")[1]
    #                     allSensorsDict["payload_hex"] = response_ok[0]["value"] #DEBUG: "000113ec00370010000000000000000000000000"
    #         else:
    #             print("Request failed with status code:", response.status_code)
    #     except requests.exceptions.RequestException as e:
    #         # Handle request exceptions (e.g., connection errors)
    #         print("Request error:", e)

    return allSensorsDict

# Get historical sensor values from WaziGates API
def getHistoricalSensorValues(url, body):
    global Target_url
    global Id
    global Gps_info
    global Threshold

    # Array that holds a list of dicts
    connected_data = []
    # Array holds device ids
    deviceAndSensorIds = []

    # Parse the query parameters from the URL
    #parsed_url = urlparse(url)

    # Retrieve the list of deviceAndSensorIds from the 'selectedOptions' query parameter
    #deviceAndSensorIds = [param[1] for param in parse_qsl(parsed_url.query) if param[0] == 'selectedOptions']

    # # Iterate through the query parameters, maybe switch?
    # for param in parse_qsl(parsed_url.query):
    #     if param[0] == 'selectedOptions':
    #         deviceAndSensorIds.append(param[1])
    #     elif param[0] == 'url':
    #         Target_url = param[1]
    #     elif param[0] == 'id':
    #         Id = param[1]
    #     elif param[0] == 'gps':
    #         Gps_info = param[1]
    #     elif param[0] == 'thres':
    #         Threshold = int(param[1])

    # Parse the query parameters from Body
    parsed_data = parse_qs(body.decode('utf-8'))

    deviceAndSensorIds = parsed_data.get('selectedOptions', [])
    Target_url = parsed_data.get('url', [])[0]
    Id = parsed_data.get('id', [])[0]
    Gps_info = parsed_data.get('gps', [])[0]
    usr = parsed_data.get('usr')[0]
    passw = parsed_data.get('passw')[0]
    Auth = parsed_data.get('auth')[0]

    # iterate all sensor devices
    #for sensor in deviceAndSensorIds[0]:
    #To wazigate:   curl -X GET "http://192.168.189.11/devices/6526644968f319084a8c67b6/sensors/6526645168f319084a8c67b7/values" -H "accept: application/json"
    #to APP:                    http://localhost:8080/getHistoricalSensorValues?selectedOptions=6318a1ba1d41c836b53718ac%20/%206318a1e31d41c836b53718ad
    
    api_url = DeviceApiUrl + deviceAndSensorIds[0].split('/')[0] + "/sensors/" + deviceAndSensorIds[0].split('/')[1] + "/values"

    try:
        # Send a GET request to the API
        response = requests.get(api_url)

        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            # The response content contains the data from the API
            data = response.json()

            for value in data:
                # Call getSensorAtTheSameTime with all selected sensors and one value (and timestamp) at a time  
                connected_data.append(getSensorAtTheSameTime(deviceAndSensorIds, value))


            #print("Response for: " + sensor + "/n Data: " + data)
        else:
            print("Request failed with status code:", response.status_code)
    except requests.exceptions.RequestException as e:
        # Handle request exceptions (e.g., connection errors)
        print("Request error:", e)

    # TODO: Create JSON obeject and do POST to endpoint 
    print("Connected data to POST: ", connected_data)

    # Send message to endpoint
    if Auth == "jwt": # ALso token can be old: check if it is still valid
        token = get_jwt_token(usr, passw)
        if token:
            post_message_to_endpoint(connected_data, token) #TODO:needs to write a function to MULTIPLE send data to endpoint
    else:
        resp = postMessagesToEndpoint(connected_data, usr, passw)
        print(resp)

    return 200, b"", []

usock.routerPOST("/api/getHistoricalSensorValues", getHistoricalSensorValues)

class WorkerThread(threading.Thread):
    def __init__(self, DeviceAndSensorIdsSync, usr, passw):
        super(WorkerThread, self).__init__()
        self.DeviceAndSensorIdsSync = DeviceAndSensorIdsSync
        self.usr = usr
        self.passw = passw
        self._stop_event = threading.Event()

    def on_stop(self):
        self._stop_event.set()

    def run(self):
        # MQTT settings
        MQTT_BROKER = "wazigate"
        MQTT_PORT = 1883
        MQTT_TOPIC = "devices/+"

        # MQTT on_connect callback
        def on_connect(client, userdata, flags, rc):
            print("Connected to MQTT broker with result code " + str(rc))
            client.subscribe(MQTT_TOPIC)

        # MQTT on_message callback
        def on_message(client, userdata, msg):
            if not self._stop_event.is_set():
                alreadySyncedDevices = []
                try:
                    for deviceAndSensor in self.DeviceAndSensorIdsSync:
                        currentDeviceId = deviceAndSensor.split("/")[0]
                        currentDeviceIdInTopic = msg.topic.split("/")[1]
                        if currentDeviceId == currentDeviceIdInTopic and currentDeviceId not in alreadySyncedDevices:
                            # Add to list to prevent duplicates
                            alreadySyncedDevices.append(currentDeviceId)
                            print("The device " + currentDeviceId + " is set to sync.")

                            # Make API Call for first in list
                            api_url = DeviceApiUrl + self.DeviceAndSensorIdsSync[0].split('/')[0] + "/sensors/" + self.DeviceAndSensorIdsSync[0].split('/')[1] + "/values"

                            try:
                                # Send a GET request to the API
                                response = requests.get(api_url)

                                # Check if the request was successful (status code 200)
                                if response.status_code == 200:
                                    # The response content contains the data from the API
                                    data = response.json()
                                else:
                                    print("Request failed with status code:", response.status_code)
                            except requests.exceptions.RequestException as e:
                                # Handle request exceptions (e.g., connection errors)
                                print("Request error:", e)

                            # Use helper to retrieve other sensors from device
                            deviceDict = getSensorAtTheSameTime(self.DeviceAndSensorIdsSync, data[len(data) - 1])
                            # Send message to endpoint
                            if Auth == "jwt": # ALso token can be old: check if it is still valid
                                token = get_jwt_token(self.usr, self.passw)
                                if token:
                                    post_message_to_endpoint(deviceDict, token)
                            else:
                                postMessageToEndpoint(deviceDict, self.usr, self.passw)
                            #resp = postMessageToEndpoint(deviceDict, self.usr, self.passw)

                    alreadySyncedDevices.clear()

                except Exception as e:
                    print("Error:", str(e))

        # Introduce list to prevent doubled sync
        SyncedDevices.append(self.DeviceAndSensorIdsSync[0].split("/")[0])

        # Create an MQTT client
        client = mqtt.Client()
        client.on_connect = on_connect
        client.on_message = on_message

        # Connect to the MQTT broker
        client.connect(MQTT_BROKER, MQTT_PORT, 60)

        # Start the MQTT client's network loop
        client.loop_start()

        while not self._stop_event.is_set():
            # Periodically check the stop event and exit the loop if set
            time.sleep(1)

        # Stop the MQTT client's network loop when the thread is stopped
        client.loop_stop()


def getFutureValues(url, body):
    global Threads
    global ThreadId
    global Target_url
    global Id
    global Gps_info
    global Threshold
    global DeviceAndSensorIdsSync
    global SyncedDevices
    global Auth

    # # Parse the query parameters from the URL
    # parsed_url = urlparse(url)

    # # Iterate through the query parameters, maybe switch?
    # for param in parse_qsl(parsed_url.query):
    #     if param[0] == 'selectedOptions':
    #         DeviceAndSensorIdsSync.append(param[1])
    #     elif param[0] == 'url':
    #         Target_url = param[1]
    #     elif param[0] == 'id':
    #         Id = param[1]
    #     elif param[0] == 'gps':
    #         Gps_info = param[1]
    #     elif param[0] == 'thres':
    #         Threshold = int(param[1])

    # Parse the query parameters from Body
    parsed_data = parse_qs(body.decode('utf-8'))

    DeviceAndSensorIdsSync = parsed_data.get('selectedOptions', [])
    Target_url = parsed_data.get('url', [])[0]
    Id = parsed_data.get('id', [])[0]
    Gps_info = parsed_data.get('gps', [])[0]
    usr = parsed_data.get('usr')[0]
    passw = parsed_data.get('passw')[0]
    Auth = parsed_data.get('auth')[0]

    # Create a thread
    if DeviceAndSensorIdsSync[0].split("/")[0] not in SyncedDevices:
        thread = WorkerThread(DeviceAndSensorIdsSync, usr, passw)

        # Append thread to list
        Threads.append(thread)

        # Start the thread
        thread.start()

        # Save data to preserve given information on reload or resume of docker container (reboot) 
        saveConfig(usr, passw)

        return 200, b"", []
    else:
        return 400, b"One or all devices had been already added to the sync!\nIf you want to continue the current synchronization with the displayed configuration, press the Okay button.\nTo stop the current synchronization press the Cancel button.", []

usock.routerPOST("/api/getFutureValues", getFutureValues)

# Just kill all threads and stop sync
def stopSync(url, body):
    global SyncedDevices
    global Threads

    for thread in Threads:
        # To stop the thread by its ID:
        #kill_thread(thread)
        thread.on_stop()
        thread.join()  # Wait for thread to fully stop before continuing

    # Clear list of running threads
    Threads = []

    # Empty list of devices
    SyncedDevices = []

    # Delete config file
    try:
        # Attempt to remove the file
        os.remove(ConfigPath)
        print(f"File {ConfigPath} has been successfully deleted.")
    except FileNotFoundError:
        print(f"File {ConfigPath} not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

    return 200, b"The synchronisation was stopped! Click on the \"Sync all future sensor values\" button to restart the sync again.", []

usock.routerGET("/api/stopSync", stopSync)

#------------------#


if __name__ == "__main__":
    resumeAfterRestart()
    usock.start() 
