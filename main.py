# TODO: delete ports from URLs


#!/usr/bin/python
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlparse
import requests
import urllib
import usock
import os
import pathlib
import paho.mqtt.client as mqtt
import json
import threading

#---------------------#

usock.sockAddr = "proxy.sock"

# URL of API to retrive devices
DeviceApiUrl = "http://localhost:8080/devices/"

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

# Database settings
DB_API_KEY = ""



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


def time(url, body=""):
    import datetime
    dateAndTime = datetime.datetime.now().strftime("%B %d %Y %H:%M:%S")

    out = str.encode(dateAndTime)
    return 200, out, []


usock.routerGET("/time", time)

#------------------#
# Helper function to create json for one message and send to endpoint
def postMessageToEndpoint(data):
    # Convert the dictionary to JSON format
    json_data = json.dumps(data)
    
    # Forward data to the database
    headers = {"Authorization": "Bearer " + DB_API_KEY}
    response = requests.post(Target_url, json=json_data, headers=headers)

    m = ""
    if response.status_code == 200:
        m = "Data forwarded to the database successfully"
    else:
        m = "Failed to forward data to the database:" + str(response.status_code)
    print(m)
    return m
    

# Helper function to create json for multiple messages and send to endpoint
def postMessagesToEndpoint(connected_data):
    # Iterate through the list and send each dictionary as a JSON POST request
    for dictionary in connected_data:
        # Convert the dictionary to JSON format
        json_data = json.dumps(dictionary)
        
        # Send a POST request with the JSON data to the database endpoint
        response = requests.post(Target_url, json=json_data)
        
        # Check the response status (optional)
        m = ""
        if response.status_code == 200:
            m += "Data forwarded to the database successfully"
        else:
            m += "Failed to forward data to the database:" + str(response.status_code)
    print(m)
    return m

# Helper to search other sensor values and 
def getSensorAtTheSameTime(deviceAndSensorIds, dataOfFirstSensor):
    # TODO: USE THE DECODER NAMES -> TELL THEM, handle case if there are multiple sensor values for a timespan
    mapping = {
        "time": "timeStamp",
        "sensorId": "sensorId",
        "lon": "longitude",
        "lat": "latitude",
        "Air Temperature": "airTemp",
        "Air Humidity": "airHum",
        "Barometric Pressure": "pressure",
        "Wind Speed": "windSpeed",
        "Wind Direction Sensor": "windDirection",
        "Light Intensity": "lightIntensity",
        "UV Index": "uvIndex",
        "Rain Gauge": "rainfall"
    }

    # Dict to return in the end
    allSensorsDict = {
            "timeStamp": None,
            "sensorId": None,
            "longitude": None,
            "latitude": None,
            "airTemp": None,
            "airHum": None,
            "pressure": None,
            "windSpeed": None,
            "windDirection": None,
            "lightIntensity": None,
            "uvIndex": None,
            "rainfall": None
    }

    # Get time of first sensor in list
    time = dataOfFirstSensor['time']
    # Set time of the first selected sensor as time of the dict
    allSensorsDict["timeStamp"] = time
    # Set given sensor id to dict
    allSensorsDict["sensorId"] = Id
    # Set GPS coordinates
    coordinates = Gps_info.split(",")
    allSensorsDict["longitude"] = coordinates[1]
    allSensorsDict["latitude"] = coordinates[0]
    # Parse the ISO string into a datetime object
    dateObject = datetime.fromisoformat(time)
    # Subtract and add 5 seconds to get interval
    fromObject = dateObject - timedelta(seconds=Threshold)
    toObject = dateObject + timedelta(seconds=Threshold)

    # Search all other choosen sensors to see if there are occurances too
    for sensor in deviceAndSensorIds:
        # Create URL for API call
        api_url = DeviceApiUrl + sensor.split('/')[0] + "/sensors/" + sensor.split('/')[1] + "/values?from=" + fromObject.isoformat() + "&to=" + toObject.isoformat()
        # Parse the URL
        parsed_url = urllib.parse.urlsplit(api_url)

        # Encode the query parameters
        encoded_query = urllib.parse.quote(parsed_url.query, safe='=&')

        # Reconstruct the URL with the encoded query
        encoded_url = urllib.parse.urlunsplit((parsed_url.scheme, 
                                                parsed_url.netloc, 
                                                parsed_url.path, 
                                                encoded_query, 
                                                parsed_url.fragment))

        try:
            # Send a GET request to the API
            response = requests.get(encoded_url)

            # Check if the request was successful (status code 200)
            if response.status_code == 200:
                # The response content contains the data from the API
                response_ok = response.json()

                # Add values to the all_Sensors_dict
                if len(response_ok) != 0:
                    nameToAdd = mapping[sensor.split("/")[1]]
                    allSensorsDict[nameToAdd] = response_ok[0]["value"]
            else:
                print("Request failed with status code:", response.status_code)
        except requests.exceptions.RequestException as e:
            # Handle request exceptions (e.g., connection errors)
            print("Request error:", e)

    return allSensorsDict

# Get historical sensor values from WaziGates API
def getHistoricalSensorValues(url, body=""):
    global Target_url
    global Id
    global Gps_info
    global Threshold

    # Array that holds a list of dicts
    connected_data = []
    # Array holds device ids
    deviceAndSensorIds = []

    # Parse the query parameters from the URL
    parsed_url = urlparse(url)

    # Retrieve the list of deviceAndSensorIds from the 'selectedOptions' query parameter
    #deviceAndSensorIds = [param[1] for param in parse_qsl(parsed_url.query) if param[0] == 'selectedOptions']


    # Iterate through the query parameters, maybe switch?
    for param in parse_qsl(parsed_url.query):
        if param[0] == 'selectedOptions':
            deviceAndSensorIds.append(param[1])
        elif param[0] == 'url':
            Target_url = param[1]
        elif param[0] == 'id':
            Id = param[1]
        elif param[0] == 'gps':
            Gps_info = param[1]
        elif param[0] == 'thres':
            Threshold = int(param[1])

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
    resp = postMessagesToEndpoint(connected_data)


    return 200, None, []

usock.routerGET("/api/getHistoricalSensorValues", getHistoricalSensorValues)

def workerToSync(thread_id, url):
    global Target_url
    global Id
    global Gps_info
    global Threshold
    global DeviceAndSensorIdsSync
    global SyncedDevices

    # Parse the query parameters from the URL
    parsed_url = urlparse(url)

    # Iterate through the query parameters, maybe switch?
    for param in parse_qsl(parsed_url.query):
        if param[0] == 'selectedOptions':
            DeviceAndSensorIdsSync.append(param[1])
        elif param[0] == 'url':
            Target_url = param[1]
        elif param[0] == 'id':
            Id = param[1]
        elif param[0] == 'gps':
            Gps_info = param[1]
        elif param[0] == 'thres':
            Threshold = int(param[1])

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
        alreadySyncedDevices = []
        try:
            # Decode the incoming MQTT message
            message = msg.payload.decode("utf-8")

            for deviceAndSensor in DeviceAndSensorIdsSync:
                currentDeviceId = deviceAndSensor.split("/")[0]
                currentDeviceIdInTopic = msg.topic.split("/")[1]
                if currentDeviceId == currentDeviceIdInTopic and currentDeviceId not in alreadySyncedDevices:
                    # Add to list to prevent duplicates
                    alreadySyncedDevices.append(currentDeviceId)
                    print("The device " + currentDeviceId + " is set to sync.")

                    # Make API Call for first in list
                    api_url = DeviceApiUrl + DeviceAndSensorIdsSync[0].split('/')[0] + "/sensors/" + DeviceAndSensorIdsSync[0].split('/')[1] + "/values"

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

                    deviceDict = getSensorAtTheSameTime(DeviceAndSensorIdsSync, data[len(data)-1])

                    resp = postMessageToEndpoint(deviceDict)

            alreadySyncedDevices.clear()    

        except Exception as e:
            print("Error:", str(e))
    
    if DeviceAndSensorIdsSync[0].split("/")[0] not in SyncedDevices:
        # Introduce list to prevent doubled sync
        SyncedDevices.append(DeviceAndSensorIdsSync[0].split("/")[0])

        # Create an MQTT client
        client = mqtt.Client()
        client.on_connect = on_connect
        client.on_message = on_message

        # Connect to the MQTT broker
        client.connect(MQTT_BROKER, MQTT_PORT, 60)

        # Start the MQTT client's network loop
        client.loop_forever()
    else:
        print("One or all devices had been already added to the sync!")

def getFutureValues(url, body=""):
    global Threads
    global ThreadId

    # Create a thread
    thread = threading.Thread(target=workerToSync, args=(ThreadId, url))
    ThreadId += 1

    # Append thread to list
    Threads.append(thread)

    # Start the thread
    thread.start()

    # Those threads can run forever, so no need to wait until they finished

    return 200, None, []

usock.routerGET("/api/getFutureValues", getFutureValues)

#------------------#


if __name__ == "__main__":
    usock.start()
