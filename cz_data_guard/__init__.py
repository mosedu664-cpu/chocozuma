# -*- coding: utf-8 -*-
from . import models
from . import controllers


def post_init_hook(env):
    env['res.users']._cz_enforce_export_policy(strict=True)
