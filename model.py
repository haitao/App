#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
Models for user, blog, comment.
'''
import time, uuid

from db.db import next_id
from db.orm import Model, StringField, BooleanField, FloatField, TextField

