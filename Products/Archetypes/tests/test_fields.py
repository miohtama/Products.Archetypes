import unittest
# trigger zope import
from test_classgen import Dummy as BaseDummy

from Products.Archetypes.public import *
from Products.Archetypes.config import PKG_NAME
from Products.Archetypes import listTypes
from Products.Archetypes.utils import DisplayList
from Products.Archetypes import Field
from OFS.Image import File
from DateTime import DateTime

import unittest

fields = ['ObjectField', 'StringField', 
          'FileField', 'TextField', 'DateTimeField', 'LinesField',
          'IntegerField', 'FloatField', 'FixedPointField',
          'BooleanField',
          # 'ReferenceField', 'ComputedField', 'CMFObjectField', 'ImageField'
          ]

field_instances = []
for f in fields:
    field_instances.append(getattr(Field, f)(f.lower()))

field_values = {'objectfield':'objectfield',
                'stringfield':'stringfield',
                'filefield':'filefield',
                'textfield':'textfield',
                'datetimefield':'2003-01-01',
                'linesfield':'bla\nbla',
                'integerfield':'1',
                'floatfield':'1.5',
                'fixedpointfield': '1.5',
                'booleanfield':'1'}

expected_values = {'objectfield':'objectfield',
                   'stringfield':'stringfield',
                   'filefield':'filefield',
                   'textfield':'textfield',
                   'datetimefield':DateTime('2003-01-01'),
                   'linesfield':['bla', 'bla'],
                   'integerfield': 1,
                   'floatfield': 1.5,
                   'fixedpointfield': '1.50',
                   'booleanfield': 1}


schema = Schema(tuple(field_instances))

class Dummy(BaseDummy):
    schema = schema

class FakeRequest:
    other = {}
    form = {}

class ProcessingTest( unittest.TestCase ):

    def setUp(self):
        registerType(Dummy)
        content_types, constructors, ftis = process_types(listTypes(), PKG_NAME)
        self._dummy = Dummy(oid='dummy')
        self._dummy.initializeArchetype()

    def test_processing(self):
        dummy = self._dummy
        request = FakeRequest()
        request.form.update(field_values)
        dummy.REQUEST = FakeRequest()
        dummy.processForm(data=1)
        for k, v in expected_values.items():
            got = dummy.Schema()[k].get(dummy)
            if isinstance(got, File):
                got = str(got)
            self.assertEquals(got, v, '[%r] != [%r]'%(got, v))

    def test_processing_fieldset(self):
        dummy = self._dummy
        request = FakeRequest()
        request.form.update(field_values)
        request.form['fieldset'] = 'default'
        dummy.REQUEST = FakeRequest()
        dummy.processForm()
        for k, v in expected_values.items():
            got = dummy.Schema()[k].get(dummy)
            if isinstance(got, File):
                got = str(got)
            self.assertEquals(got, v, '[%r] != [%r]'%(got, v))

    def tearDown(self):
        del self._dummy

def test_suite():
    return unittest.TestSuite((
        unittest.makeSuite(ProcessingTest),
        ))

if __name__ == '__main__':
    unittest.main()