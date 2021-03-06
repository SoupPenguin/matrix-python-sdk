# -*- coding: utf-8 -*-
# Copyright 2015 OpenMarket Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from .api import MatrixHttpApi, MatrixRequestError
from threading import Thread
import sys
# TODO: Finish implementing this.


class MatrixClient(object):
    """ WORK IN PROGRESS
    The client API for Matrix. For the raw HTTP calls, see MatrixHttpApi.

    Usage (new user):
        client = MatrixClient("https://matrix.org")
        token = client.register_with_password(username="foobar",
            password="monkey")
        room = client.create_room("myroom")
        room.send_image(file_like_object)

    Usage (logged in):
        client = MatrixClient("https://matrix.org", token="foobar")
        rooms = client.get_rooms()  # NB: From initial sync
        client.add_listener(func)  # NB: event stream callback
        rooms[0].add_listener(func)  # NB: callbacks just for this room.
        room = client.join_room("#matrix:matrix.org")
        response = room.send_text("Hello!")
        response = room.kick("@bob:matrix.org")

    Incoming event callbacks (scopes):

        def user_callback(user, incoming_event):
            pass

        def room_callback(room, incoming_event):
            pass

        def global_callback(incoming_event):
            pass

    """

    def __init__(self, base_url, token=None, valid_cert_check=True):
        self.api = MatrixHttpApi(base_url, token)
        self.api.validate_certificate(valid_cert_check)
        self.listeners = []
        self.rooms = {
            # room_id: Room
        }
        if token:
            self._sync()

    def register_with_password(self, username, password, limit=1):
        response = self.api.register(
            "m.login.password", user=username, password=password
        )
        self.user_id = response["user_id"]
        self.token = response["access_token"]
        self.hs = response["home_server"]
        self.api.token = self.token
        self._sync(limit)
        return self.token

    def login_with_password(self, username, password, limit=1):
        response = self.api.login(
            "m.login.password", user=username, password=password
        )
        self.user_id = response["user_id"]
        self.token = response["access_token"]
        self.hs = response["home_server"]
        self.api.token = self.token
        self._sync(limit)
        return self.token

    def create_room(self, alias=None, is_public=False, invitees=()):
        response = self.api.create_room(alias, is_public, invitees)
        return self._mkroom(response["room_id"])

    def join_room(self, room_id_or_alias):
        response = self.api.join_room(room_id_or_alias)
        room_id = (
            response["room_id"] if "room_id" in response else room_id_or_alias
        )
        return self._mkroom(room_id)

    def get_rooms(self):
        return self.rooms

    def add_listener(self, callback):
        self.listeners.append(callback)

    def listen_for_events(self, timeout=30000):
        response = self.api.event_stream(self.end, timeout)
        self.end = response["end"]

        for chunk in response["chunk"]:
            for listener in self.listeners:
                listener(chunk)
            if "room_id" in chunk:
                if chunk["room_id"] not in self.rooms:
                    self._mkroom(chunk["room_id"])
                self.rooms[chunk["room_id"]].events.append(chunk)
                for listener in self.rooms[chunk["room_id"]].listeners:
                    listener(chunk)

    def listen_forever(self, timeout=30000):
        while(True):
            self.listen_for_events(timeout)

    def start_listener_thread(self, timeout=30000):
        try:
            thread = Thread(target=self.listen_forever, args=(timeout, ))
            thread.daemon = True
            thread.start()
        except:
            e = sys.exc_info()[0]
            print("Error: unable to start thread. " + str(e))

    def upload(self,content,content_type):
        response = self.api.media_upload(content,content_type)["content_uri"]
        return response

    def _mkroom(self, room_id):
        self.rooms[room_id] = Room(self, room_id)
        return self.rooms[room_id]

    def _sync(self, limit=1):
        response = self.api.initial_sync(limit)
        try:
            self.end = response["end"]
            for room in response["rooms"]:
                self._mkroom(room["room_id"])

                current_room = self.get_rooms()[room["room_id"]]
                for chunk in room["messages"]["chunk"]:
                    current_room.events.append(chunk)

                for state_event in room["state"]:
                    if "type" in state_event and state_event["type"] == "m.room.name":
                        current_room.name = state_event["content"]["name"]
                    if "type" in state_event and state_event["type"] == "m.room.topic":
                        current_room.topic = state_event["content"]["topic"]
                    if "type" in state_event and state_event["type"] == "m.room.aliases":
                        current_room.aliases = state_event["content"]["aliases"]

        except KeyError:
            pass


class Room(object):

    def __init__(self, client, room_id):
        self.room_id = room_id
        self.client = client
        self.listeners = []
        self.events = []
        self.name = None
        self.aliases = []
        self.topic = None

    def send_text(self, text):
        return self.client.api.send_message(self.room_id, text)

    def send_emote(self, text):
        return self.client.api.send_emote(self.room_id, text)

    def send_image(self,url,size,mimetype,width=500,height=500):
        return self.client.api.send_content(self.room_id, url,"image",size,mimetype,width,height)

    def send_video(self,url,size,mimetype):
        return self.client.api.send_content(self.room_id, url,"video",size,mimetype,640,480)

    def add_listener(self, callback):
        self.listeners.append(callback)

    def get_events(self):
        return self.events

    def invite_user(self, user_id):
        """Invite user to this room

        Return True if the invitation was sent
        """
        try:
            response = self.client.api.invite_user(self.room_id, user_id)
            return True
        except MatrixRequestError:
            return False

    def kick_user(self, user_id, reason=""):
        try:
            response = self.client.api.kick_user(self.room_id, user_id)
            return True
        except MatrixRequestError:
            return False

    def ban_user(self, user_id, reason):
        try:
            response = self.client.api.ban_user(self.room_id, user_id, reason)
            return True
        except MatrixRequestError:
            return False

    def leave(self, user_id):
        try:
            response = self.client.api.leave_room(self.room_id)
            self.client.rooms.remove(self.room_id)
            return True
        except MatrixRequestError:
            return False

    def update_room_name(self):
        """Get room name

        Return True if the room name changed, False if not
        """
        try:
            response = self.client.api.get_room_name(self.room_id)
            if "name" in response and response["name"] != self.name:
                self.name = response["name"]
                return True
            else:
                return False
        except MatrixRequestError:
            return False

    def update_room_topic(self):
        """Get room topic

        Return True if the room topic changed, False if not
        """
        try:
            response = self.client.api.get_room_topic(self.room_id)
            if "topic" in response and response["topic"] != self.topic:
                self.topic = response["topic"]
                return True
            else:
                return False
        except MatrixRequestError:
            return False

    def update_aliases(self):
        """Get aliases information from room state

        Return True if the aliases changed, False if not
        """
        try:
            response = self.client.api.get_room_state(self.room_id)
            for chunk in response:
                if "content" in chunk and "aliases" in chunk["content"]:
                    if chunk["content"]["aliases"] != self.aliases:
                        self.aliases = chunk["content"]["aliases"]
                        return True
                    else:
                        return False
        except MatrixRequestError:
            return False
