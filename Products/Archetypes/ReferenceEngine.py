import os
from types import StringType, UnicodeType
import time
import urllib

from Acquisition import aq_base

from Products.Archetypes.debug import log, log_exc
from Products.Archetypes.interfaces.referenceable import IReferenceable
from Products.Archetypes.interfaces.referenceengine import \
    IReference, IContentReference

from Products.Archetypes.utils import unique, make_uuid, getRelURL, getRelPath
from Products.Archetypes.config import UID_CATALOG, \
     REFERENCE_CATALOG,UUID_ATTR, REFERENCE_ANNOTATION
from Products.Archetypes.exceptions import ReferenceException

from Acquisition import aq_base, aq_parent, aq_inner
from AccessControl import ClassSecurityInfo
from Acquisition import aq_base
from ExtensionClass import Base
from OFS.SimpleItem import SimpleItem
from OFS.ObjectManager import ObjectManager

from Globals import InitializeClass, DTMLFile
from Products.CMFCore.utils import getToolByName
from Products.CMFCore.utils import UniqueObject
from Products.CMFCore import CMFCorePermissions
from Products.BTreeFolder2.BTreeFolder2 import BTreeFolder2
from Products.PageTemplates.PageTemplateFile import PageTemplateFile
from Products.ZCatalog.ZCatalog import ZCatalog
from Products.ZCatalog.Catalog import Catalog
from Products.ZCatalog.CatalogBrains import AbstractCatalogBrain
from Products import CMFCore
from ZODB.POSException import ConflictError

import zLOG
import sys

_www = os.path.join(os.path.dirname(__file__), 'www')
_catalog_dtml = os.path.join(os.path.dirname(CMFCore.__file__), 'dtml')

STRING_TYPES = (StringType, UnicodeType)


from Referenceable import Referenceable


class Reference(Referenceable, SimpleItem):
    ## Added base level support for referencing References
    ## They respond to the UUID protocols, but are not
    ## catalog aware. This means that you can't move/rename
    ## reference objects and expect them to work, but you can't
    ## do this anyway. However they should fine the correct
    ## events when they are added/deleted, etc

    __implements__ = Referenceable.__implements__ + (IReference,)

    security = ClassSecurityInfo()
    portal_type = 'Reference'

    # XXX FIXME more security

    manage_options = (
        (
        {'label':'View', 'action':'manage_view',
         },
        )+
        SimpleItem.manage_options
        )

    security.declareProtected(CMFCorePermissions.ManagePortal,
                              'manage_view')
    manage_view = PageTemplateFile('view_reference', _www)

    def __init__(self, id, sid, tid, relationship, **kwargs):
        self.id = id
        setattr(self, UUID_ATTR,  id)

        self.sourceUID = sid
        self.targetUID = tid
        self.relationship = relationship

        self.__dict__.update(kwargs)

    def __repr__(self):
        return "<Reference sid:%s tid:%s rel:%s>" %(self.sourceUID, self.targetUID, self.relationship)

    def UID(self):
        """the uid method for compat"""
        return getattr(self, UUID_ATTR)

    ###
    # Convenience methods
    def getSourceObject(self):
        tool = getToolByName(self, UID_CATALOG)
        if not tool: return ''
        brains = tool(UID=self.sourceUID)
        if brains:
            return brains[0].getObject()
        raise AttributeError('sourceObject')

    def getTargetObject(self):
        tool = getToolByName(self, UID_CATALOG, None)
        if not tool: return ''
        brains = tool(UID=self.targetUID)
        if brains:
            return brains[0].getObject()
        raise AttributeError('targetObject')

    ###
    # Catalog support
    def targetId(self):
        target = self.getTargetObject()
        if target:
            return target.getId()
        return ''

    def targetTitle(self):
        target = self.getTargetObject()
        if target:
            return target.Title()
        return ''

    def Type(self):
        return self.__class__.__name__

    ###
    # Policy hooks, subclass away
    def addHook(self, tool, sourceObject=None, targetObject=None):
        #to reject the reference being added raise a ReferenceException
        pass

    def delHook(self, tool, sourceObject=None, targetObject=None):
        #to reject the delete raise a ReferenceException
        pass

    ###
    # OFS Operations Policy Hooks
    # These Hooks are experimental and subject to change
    def beforeTargetDeleteInformSource(self):
        """called before target object is deleted so
        the source can have a say"""
        pass

    def beforeSourceDeleteInformTarget(self):
        """called when the refering source Object is
        about to be deleted"""
        pass

    def manage_afterAdd(self, item, container):
        Referenceable.manage_afterAdd(self, item, container)
        
        # when copying a full site containe is the container of the plone site
        # and item is the plone site (at least for objects in portal root)
        base = container
        try:
            rc = getToolByName(base, REFERENCE_CATALOG)
        except:
            base = item
            rc = getToolByName(base, REFERENCE_CATALOG)
        url = getRelURL(base, self.getPhysicalPath())
        rc.catalog_object(self, url)


    def manage_beforeDelete(self, item, container):
        Referenceable.manage_beforeDelete(self, item, container)
        rc  = getToolByName(container, REFERENCE_CATALOG)
        url = getRelURL(container, self.getPhysicalPath())
        rc.uncatalog_object(url)



InitializeClass(Reference)

REFERENCE_CONTENT_INSTANCE_NAME = 'content'

class ContentReference(Reference, ObjectManager):
    '''Subclass of Reference to support contentish objects inside references '''

    __implements__ = Reference.__implements__ + (IContentReference,)

    security = ClassSecurityInfo()
    # XXX FIXME more security

    def addHook(self, *args, **kw):
        #creates the content instance
        if type(self.contentType) in (type(''),type(u'')):
            #type given as string
            tt=getToolByName(self,'portal_types')
            tt.constructContent(self.contentType,self,REFERENCE_CONTENT_INSTANCE_NAME)
        else:
            #type given as class
            setattr(self.REFERENCE_CONTENT_INSTANCE_NAME,self.contentType(REFERENCE_CONTENT_INSTANCE_NAME))
            getattr(self.REFERENCE_CONTENT_INSTANCE_NAME)._md=PersistentMapping()

    def getContentObject(self):
        return getattr(self,REFERENCE_CONTENT_INSTANCE_NAME)

InitializeClass(ContentReference)

class ContentReferenceCreator:
    '''Helper class to construct ContentReference instances based
       on a certain content type '''

    security = ClassSecurityInfo()

    def __init__(self,contentType):
        self.contentType=contentType

    def __call__(self,*args,**kw):
        #simulates the constructor call to the reference class in addReference
        res=ContentReference(*args,**kw)
        res.contentType=self.contentType

        return res

InitializeClass(ContentReferenceCreator)

# The brains we want to use
class UIDCatalogBrains(AbstractCatalogBrain):
    """fried my little brains"""

    security = ClassSecurityInfo()

    def getObject(self, REQUEST=None):
        """
        Used to resolve UIDs into real objects. This also must be
        annotation aware. The protocol is:
        We have the path to an object. We get this object. If its
        UID is not the UID in the brains then we need to pull it
        from the reference annotation and return that object

        Thus annotation objects store the path to the source object
        """
        obj = None
        try:
            path = self.getPath()
            try:
                portal = getToolByName(self, 'portal_url').getPortalObject()
                obj = portal.unrestrictedTraverse(self.getPath())
                obj = aq_inner( obj )
            except ConflictError:
                raise
            except: #NotFound # XXX bare exception
                pass

            if not obj:
                if REQUEST is None:
                    REQUEST = self.REQUEST
                obj = self.aq_parent.resolve_url(self.getPath(), REQUEST)

            return obj
        except ConflictError:
            raise
        except:
            #import traceback
            #traceback.print_exc()
            zLOG.LOG('UIDCatalogBrains', zLOG.INFO, 'getObject raised an error',
                     error=sys.exc_info())
            pass

InitializeClass(UIDCatalogBrains)

class ReferenceCatalogBrains(UIDCatalogBrains):
    pass


class PluggableCatalog(Catalog):
    # Catalog overrides
    # smarter brains, squirrely traversal

    security = ClassSecurityInfo()
    # XXX FIXME more security

    def useBrains(self, brains):
        """Tricky brains overrides, we need to use our own class here
        with annotation support
        """
        class plugbrains(self.BASE_CLASS, brains):
            pass

        schema = self.schema
        scopy = schema.copy()

        scopy['data_record_id_']=len(schema.keys())
        scopy['data_record_score_']=len(schema.keys())+1
        scopy['data_record_normalized_score_']=len(schema.keys())+2

        plugbrains.__record_schema__ = scopy

        self._v_brains = brains
        self._v_result_class = plugbrains

InitializeClass(PluggableCatalog)

class UIDBaseCatalog(PluggableCatalog):
    BASE_CLASS = UIDCatalogBrains

class ReferenceBaseCatalog(PluggableCatalog):
    BASE_CLASS = ReferenceCatalogBrains

class ReferenceResolver(Base):

    security = ClassSecurityInfo()
    # XXX FIXME more security

    def resolve_url(self, path, REQUEST):
        """Strip path prefix during resolution, This interacts with
        the default brains.getObject model and allows and fakes the
        ZCatalog protocol for traversal
        """
        parts = path.split('/')
        # XXX REF_PREFIX is undefined
        #if parts[-1].find(REF_PREFIX) == 0:
        #    path = '/'.join(parts[:-1])

        portal_object = self.portal_url.getPortalObject()

        return portal_object.unrestrictedTraverse(path)

InitializeClass(ReferenceResolver)

class UIDCatalog(UniqueObject, ReferenceResolver, ZCatalog):
    id = UID_CATALOG
    manage_catalogFind = DTMLFile('catalogFind', _catalog_dtml)
    
    def __init__(self, id, title='', vocab_id=None, container=None):
        """We hook up the brains now"""
        ZCatalog.__init__(self, id, title, vocab_id, container)
        self._catalog = UIDBaseCatalog()


class ReferenceCatalog(UniqueObject, ReferenceResolver, ZCatalog):
    id = REFERENCE_CATALOG
    security = ClassSecurityInfo()
    manage_catalogFind = DTMLFile('catalogFind', _catalog_dtml)
    manage_options = ZCatalog.manage_options

    # XXX FIXME more security

    def __init__(self, id, title='', vocab_id=None, container=None):
        """We hook up the brains now"""
        ZCatalog.__init__(self, id, title, vocab_id, container)
        self._catalog = ReferenceBaseCatalog()

    ###
    ## Public API
    def addReference(self, source, target, relationship=None,
                     referenceClass=None, **kwargs):
        sID, sobj = self._uidFor(source)
        tID, tobj = self._uidFor(target)

        objects = self._resolveBrains(self._queryFor(sID, tID, relationship))
        if objects:
            #we want to update the existing reference
            #XXX we might need to being a subtransaction here to
            #    do this properly, and close it later
            existing = objects[0]
            if existing:
                # We can't del off self, we now need to remove it
                # from the source objects annotation, which we have
                annotation = sobj._getReferenceAnnotations()
                annotation._delObject(existing.id)


        rID = self._makeName(sID, tID)
        if not referenceClass:
            referenceClass = Reference

        referenceObject = referenceClass(rID, sID, tID, relationship,
                                         **kwargs)
        referenceObject = referenceObject.__of__(sobj)
        try:
            referenceObject.addHook(self, sobj, tobj)
        except ReferenceException:
            pass
        else:
            annotation = sobj._getReferenceAnnotations()
            # This should call manage_afterAdd
            annotation._setObject(rID, referenceObject)
            return referenceObject

    def deleteReference(self, source, target, relationship=None):
        sID, sobj = self._uidFor(source)
        tID, tobj = self._uidFor(target)

        objects = self._resolveBrains(self._queryFor(sID, tID, relationship))
        if objects:
            self._deleteReference(objects[0])

    def deleteReferences(self, object, relationship=None):
        """delete all the references held by an object"""
        for b in self.getReferences(object, relationship):
            self._deleteReference(b)

        for b in self.getBackReferences(object, relationship):
            self._deleteReference(b)

    def getReferences(self, object, relationship=None):
        """return a collection of reference objects"""
        sID, sobj = self._uidFor(object)
        brains = self._queryFor(sid=sID, relationship=relationship)
        return self._resolveBrains(brains)

    def getBackReferences(self, object, relationship=None):
        """return a collection of reference objects"""
        # Back refs would be anything that target this object
        sID, sobj = self._uidFor(object)
        brains = self._queryFor(tid=sID, relationship=relationship)
        return self._resolveBrains(brains)

    def hasRelationshipTo(self, source, target, relationship):
        sID, sobj = self._uidFor(source)
        tID, tobj = self._uidFor(target)

        brains = self._queryFor(sID, tID, relationship)
        result = False
        if brains:
            referenceObject = brains[0].getObject()
            result = True

        return result

    def getRelationships(self, object):
        """
        Get all relationship types this object has TO other objects
        """
        sID, sobj = self._uidFor(object)
        brains = self._queryFor(sid=sID)
        res = {}
        for b in brains:
            res[b.relationship]=1

        return res.keys()

    def getBackRelationships(self, object):
        """
        Get all relationship types this object has FROM other objects
        """
        sID, sobj = self._uidFor(object)
        brains = self._queryFor(tid=sID)
        res = {}
        for b in brains:
            res[b.relationship]=1

        return res.keys()


    def isReferenceable(self, object):
        return (IReferenceable.isImplementedBy(object) or
                hasattr(aq_base(object), 'isReferenceable'))

    def reference_url(self, object):
        """return a url to an object that will resolve by reference"""
        sID, sobj = self._uidFor(object)
        return "%s/lookupObject?uuid=%s" % (self.absolute_url(), sID)

    def lookupObject(self, uuid, REQUEST=None):
        """Lookup an object by its uuid"""
        obj = self._objectByUUID(uuid)
        if REQUEST:
            return REQUEST.RESPONSE.redirect(obj.absolute_url())
        else:
            return obj

    #####
    ## UID register/unregister
    security.declareProtected(CMFCorePermissions.ModifyPortalContent, 'registerObject')
    def registerObject(self, object):
        self._uidFor(object)

    security.declareProtected(CMFCorePermissions.ModifyPortalContent, 'unregisterObject')
    def unregisterObject(self, object):
        self.deleteReferences(object)
        uc = getToolByName(self, UID_CATALOG)
        uc.uncatalog_object(self.getURL())


    ######
    ## Private/Internal
    def _objectByUUID(self, uuid):
        tool = getToolByName(self, UID_CATALOG)
        brains = tool(UID=uuid)
        if not brains:
            return None
        return brains[0].getObject()

    def _queryFor(self, sid=None, tid=None, relationship=None,
                  targetId=None, merge=1):
        """query reference catalog for object matching the info we are
        given, returns brains

        Note: targetId is the actual id of the target object, not its UID
        """

        q = {}
        if sid: q['sourceUID'] = sid
        if tid: q['targetUID'] = tid
        if relationship: q['relationship'] = relationship
        if targetId: q['targetId'] = targetId
        brains = self.searchResults(q, merge=merge)

        return brains


    def _uidFor(self, obj):
        # We should really check for the interface but I have an idea
        # about simple annotated objects I want to play out
        if type(obj) not in STRING_TYPES:
            uobject = aq_base(obj)
            if not self.isReferenceable(uobject):
                raise ReferenceException, "%r not referenceable" % uobject

            if not getattr(uobject, UUID_ATTR, None):
                uuid = self._getUUIDFor(uobject)
            else:
                uuid = getattr(uobject, UUID_ATTR)
        else:
            uuid = obj
            #and we look up the object
            uid_catalog = getToolByName(self, UID_CATALOG)
            brains = uid_catalog(UID=uuid)
            if brains:
                obj = brains[0].getObject()
            else:
                obj = None

        return uuid, obj

    def _getUUIDFor(self, object):
        """generate and attach a new uid to the object returning it"""
        uuid = make_uuid(object.getId())
        setattr(object, UUID_ATTR, uuid)

        return uuid

    def _deleteReference(self, referenceObject):
        try:
            sobj = referenceObject.getSourceObject()
            referenceObject.delHook(self, sobj,
                                    referenceObject.getTargetObject())
        except ReferenceException:
            pass
        else:
            annotation = sobj._getReferenceAnnotations()
            annotation._delObject(referenceObject.UID())

    def _resolveBrains(self, brains):
        objects = []
        if brains:
            objects = [b.getObject() for b in brains]
            objects = [b for b in objects if b]
        return objects

    def _makeName(self, *args):
        """get a uuid"""
        name = make_uuid(*args)
        return name

    def __nonzero__(self):
        return 1

    def _catalogReferencesFor(self,obj,path):
        if IReferenceable.isImplementedBy(obj):
            obj._catalogRefs(self)

    def _catalogReferences(self,root=None,**kw):
        ''' catalogs all references, where the optional parameter 'root' 
           can be used to specify the tree that has to be searched for references '''
           
        if not root:
            root=getToolByName(self,'portal_url').getPortalObject()

        path = '/'.join(root.getPhysicalPath())

        results = self.ZopeFindAndApply(root,
                                        search_sub=1,
                                        apply_func=self._catalogReferencesFor,
                                        apply_path=path,**kw)
            
        

    def manage_catalogFoundItems(self, REQUEST, RESPONSE, URL2, URL1,
                                 obj_metatypes=None,
                                 obj_ids=None, obj_searchterm=None,
                                 obj_expr=None, obj_mtime=None,
                                 obj_mspec=None, obj_roles=None,
                                 obj_permission=None):

        """ Find object according to search criteria and Catalog them
        """
        

        elapse = time.time()
        c_elapse = time.clock()

        words = 0
        obj = REQUEST.PARENTS[1]

        self._catalogReferences(obj,obj_metatypes=obj_metatypes,
                                 obj_ids=obj_ids, obj_searchterm=obj_searchterm,
                                 obj_expr=obj_expr, obj_mtime=obj_mtime,
                                 obj_mspec=obj_mspec, obj_roles=obj_roles,
                                 obj_permission=obj_permission)
        
        elapse = time.time() - elapse
        c_elapse = time.clock() - c_elapse

        RESPONSE.redirect(
            URL1 +
            '/manage_catalogView?manage_tabs_message=' +
            urllib.quote('Catalog Updated\n'
                         'Total time: %s\n'
                         'Total CPU time: %s'
                         % (`elapse`, `c_elapse`))
            )


InitializeClass(ReferenceCatalog)


def manage_addReferenceCatalog(self, id, title,
                               vocab_id=None, # Deprecated
                               REQUEST=None):
    """Add a ReferenceCatalog object
    """
    id=str(id)
    title=str(title)
    c=ReferenceCatalog(id, title, vocab_id, self)
    self._setObject(id, c)
    if REQUEST is not None:
        return self.manage_main(self, REQUEST,update_menu=1)

InitializeClass(ReferenceCatalog)


def manage_addUIDCatalog(self, id, title,
                         vocab_id=None, # Deprecated
                         REQUEST=None):
    """Add the UID Catalog
    """
    id = str(id)
    title = str(title)
    c = UIDCatalog(id, title, vocab_id, self)
    self._setObject(id, c)

    if REQUEST is not None:
        return self.manage_main(self, REQUEST,update_menu=1)
