""" This file contains the definitions for the less template tag """

from tempfile import NamedTemporaryFile
from ..cache import get_cache_key, get_hexdigest, get_hashed_mtime
from ..settings import LESS_EXECUTABLE, LESS_USE_CACHE, LESS_CACHE_TIMEOUT
from ..settings import LESS_OUTPUT_DIR
from ..utils import URLConverter
from django.core.cache import cache
from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.template.base import Library, Node

import glob
import logging
import os
import shlex
import subprocess
import sys

logger = logging.getLogger("less")
register = Library()


class InlineLessNode(Node):

    def __init__(self, nodelist):
        self.nodelist = nodelist

    def compile(self, source):
        source_file = NamedTemporaryFile(delete=False)
        source_file.write(source)
        source_file.close()
        args = shlex.split("%s %s" % (LESS_EXECUTABLE, source_file.name))

        p = subprocess.Popen(args, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        out, errors = p.communicate()
        os.remove(source_file.name)
        if out:
            return out.decode("utf-8")
        elif errors:
            return errors.decode("utf-8")

        return u""

    def render(self, context):
        output = self.nodelist.render(context)

        if LESS_USE_CACHE:
            cache_key = get_cache_key(get_hexdigest(output))
            cached = cache.get(cache_key, None)
            if cached is not None:
                return cached
            output = self.compile(output)
            cache.set(cache_key, output, LESS_CACHE_TIMEOUT)
            return output
        return self.compile(output)


@register.tag(name="inlineless")
def do_inlineless(parser, token):
    nodelist = parser.parse(("endinlineless",))
    parser.delete_first_token()
    return InlineLessNode(nodelist)


@register.simple_tag
def less(path):
    STATIC_URL = settings.STATIC_URL

    # locate the static file
    encoded_full_path = full_path = find(path)

    if isinstance(full_path, unicode):
        filesystem_encoding = (sys.getfilesystemencoding() or
                               sys.getdefaultencoding())
        encoded_full_path = full_path.encode(filesystem_encoding)

    # file does not exist
    if full_path is None:
        logger.error('less source file %s not found by staticfiles finders' %
                     path)
        return path

    directory, filename = os.path.split(encoded_full_path)
    output_directory = os.path.join(directory, LESS_OUTPUT_DIR)
    hashed_mtime = get_hashed_mtime(full_path)
    base_filename = os.path.splitext(filename)[0]
    compiled_filename = "%s-%s.css" % (base_filename, hashed_mtime)
    output_path = os.path.join(output_directory, compiled_filename)

    if not os.path.exists(output_path):
        command = "%s %s" % (LESS_EXECUTABLE, encoded_full_path)
        args = shlex.split(command)
        p = subprocess.Popen(args, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        out, errors = p.communicate()
        out = out.strip()
        if out:
            # if there is any output, write it to a file
            if not os.path.exists(output_directory):
                os.makedirs(output_directory)

            with open(output_path, "w+") as compiled_file:
                css_code = URLConverter(out, os.path.join(STATIC_URL,
                                                          path)).convert()
                compiled_file.write(css_code)

            # cleanup old files
            pattern = os.path.join(output_directory,
                                   "%s-*.css" % base_filename)
            old_filenames = glob.glob(pattern)
            for filename in old_filenames:
                if not filename == output_path:
                    logger.info('Removing old file %s' % filename)
                    os.remove(os.path.join(output_directory, filename))

        elif errors:
            logger.error(errors)
            return path

    output_url = os.path.join(os.path.dirname(path),
                              LESS_OUTPUT_DIR,
                              compiled_filename)
    return output_url
