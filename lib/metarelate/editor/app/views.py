# (C) British Crown Copyright 2013, Met Office
#
# This file is part of metarelate.
#
# metarelate is free software: you can redistribute it and/or 
# modify it under the terms of the GNU Lesser General Public License 
# as published by the Free Software Foundation, either version 3 of 
# the License, or (at your option) any later version.
#
# metarelate is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with metarelate. If not, see <http://www.gnu.org/licenses/>.

import collections
import copy
import hashlib
import itertools
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib

from django.shortcuts import get_object_or_404, render_to_response
from django.http import HttpResponseRedirect, HttpResponse, Http404
from django.core.urlresolvers import reverse
from django.template import RequestContext
from django.utils.html import escape 
from django.utils.safestring import mark_safe
from django.forms.formsets import formset_factory
from django.forms.models import inlineformset_factory


import forms
import metarelate
import metarelate.prefixes as prefixes
from metarelate.editor.settings import READ_ONLY
from metarelate.editor.settings import fuseki_process
from metarelate.editor.settings import ROOTUSER

def _get_branch(request):
    branch_path = request.GET.get('branch', '')
    branch = urllib.unquote(branch_path).decode('utf8')
    if branch and not branch.endswith('/'):
        branch = branch + '/'
    #20-byte hash values only
    asha = re.compile('^[a-f0-9]{40}/$')
    if branch and not asha.match(branch):
        raise ValueError('invalid branch identifier')
    return branch

def home(request):
    context = RequestContext(request)
    response = render_to_response('home.html', context)
    return response

def homegraph(request):
    response = HttpResponse(content_type="image/svg+xml")
    graph = fuseki_process.summary_graph()
    response.write(graph.create_svg())
    return response
    

def controlpanel(request):
    """
    returns a view for the editor control panelhomepage
    for interacting with the triple store
    and reporting on status
    
    """
    branch = _get_branch(request)
    branch_mappings = []
    if branch:
        branch_mappings = fuseki_process.query_branch(branch)
        branch_mappings = [bm['mapping'].rstrip('>').lstrip('<') for bm in
                           branch_mappings]
        branch_mappings = [bm.split('http://www.metarelate.net/metOcean/mapping/')[-1]
                           for bm in
                           branch_mappings]
        branch_mappings = [reverse(mapping, kwargs={'mapping_id':bm}) 
                           for bm in branch_mappings]
        branch_mappings = [{'url':'{}?branch={}'.format(bm, branch),
                            'label':bm} for bm in branch_mappings] 
    if request.method == 'POST':
        form = forms.HomeForm(request.POST)
        if form.is_valid():
            invalids = form.cleaned_data.get('validation')
            create_branch = form.cleaned_data.get('branch')
            if invalids:
                url = url_qstr(reverse('invalid_mappings'),
                                           ref=json.dumps(invalids))
                response = HttpResponseRedirect(url)
            elif create_branch:
                url = url_qstr(reverse('control_panel'), branch=create_branch)
                response = HttpResponseRedirect(url)
            elif form.cleaned_data.get('save'):
                response = HttpResponse(content_type='application/x-tar')
                with tarfile.open(name='metarelate.tar.bz', fileobj=response,
                                  mode='w:bz2') as tarf:
                    for subgraph in ['mappings.ttl', 'concepts.ttl']:
                        outstring = form.cleaned_data.get(subgraph, '')
                        outstring_io = io.BytesIO(outstring.encode('utf8'))
                        tarinfo = tarfile.TarInfo(name=subgraph)
                        tarinfo.size = len(outstring)
                        tarinfo.mtime = int(time.time())
                        tarf.addfile(tarinfo, outstring_io)

            else:
                url = url_qstr(reverse('control_panel'), branch=branch)
                #reload(forms)
                response = HttpResponseRedirect(url)
    else:
        form = forms.HomeForm()
        con_dict = {}
        con_dict['mappings'] = branch_mappings
        con_dict['control'] = {'control':'control'}
        con_dict['form'] = form
        con_dict['branch'] = branch
        con_dict['upload'] = [url_qstr(reverse('upload', 
                                               kwargs={'importer':'stashcf'}), 
                                       branch=branch)]
        context = RequestContext(request, con_dict)
        response = render_to_response('main.html', context)
    return response

def upload(request, importer):
    user = 'https://github.com/marqh'
    if importer != 'stashcf':
        raise ValueError('no matching yet')
    # find importer: get docstring
    upload_doc = 'upload a stash code to cfname and units table'
    static_dir = metarelate.site_config.get('static_dir')
    if static_dir:
        dpdir = metarelate.site_config['static_dir'].rstrip('staticData')

        sys.path.append(os.path.join(dpdir, 'lib'))

        import metarelate_metocean.upload.stashc_cfname as uploader

    branch = _get_branch(request)
    #forms.UploadForm
    if request.method == 'POST':
#        import pdb; pdb.set_trace()
        form = forms.UploadForm(request.POST, request.FILES)
        if form.is_valid():
            docfile = request.FILES['docfile']
            uploader.parse_file(fuseki_process, docfile,
                                user, branch)
            url = url_qstr(reverse('control_panel'), branch=branch)
            return HttpResponseRedirect(url)
                
    else:
        form = forms.UploadForm()
    con_dict = {'form': form, 'upload_doc': upload_doc}

    context = RequestContext(request, con_dict)
    response = render_to_response('upload_form.html', context)
    return response

def url_qstr(path, **kwargs):
    """
    helper function
    returns url for path and query string
    
    """
    return path + '?' + urllib.urlencode(kwargs)

def retrieve_mappings(request):
    # send back json string
    #requestor_path = request.GET.get('ref', '')
    #requestor = urllib.unquote(requestor_path).decode('utf8')
    #import pdb; pdb.set_trace()
    #if requestor == '':
    #    requestor = '{}'
    #requestor = json.loads(requestor)
    ## need a source and a target
    # if not requestor.get('source') of requestor.get('target'):
    ### but, do we want to throw an exception, or do we want to return a 404??
    ### to ponder
    #     return HttpResponse(404)
    # else:
    sourcetype = metarelate.Item(request.GET.get('source'))
    targettype = metarelate.Item(request.GET.get('target'))
    response = HttpResponse(content_type="")
    map_templates = json.dumps('{}')
    try:
        map_templates = fuseki_process.retrieve_mapping_templates(sourcetype, targettype)
    except Exception:
        pass
    response.write(map_templates)
    return response

def mapping_view_graph(request, mapping_id):
    """"""
    branch = _get_branch(request)
    mapping = metarelate.Mapping(None)
    mapping.shaid = mapping_id
    mapping.populate_from_uri(fuseki_process, graph=branch)
    response = HttpResponse(content_type="image/svg+xml")
    graph = mapping.dot()
    response.write(graph.create_svg())
    return response

def mapping(request, mapping_id):
    """"""
    branch = _get_branch(request)
    mapping = metarelate.Mapping(None)
    mapping.shaid = mapping_id
    mapping.populate_from_uri(fuseki_process, graph=branch)
    shaid = mapping.shaid
    form = forms.MappingMetadata(initial=mapping.__dict__)
    con_dict = {'mapping':mapping, 'shaid':shaid, 'form':form, 'branchid':branch}
    context = RequestContext(request, con_dict)
    response = render_to_response('viewmapping.html', context)
    return response


def component_view_graph(request, component_id):
    """"""
    component = metarelate.Component(None)
    component.shaid = component_id
    component.populate_from_uri(fuseki_process)
    response = HttpResponse(content_type="image/svg+xml")
    graph = component.dot()
    response.write(graph.create_svg())
    return response

def component(request, component_id):
    """"""
    component = metarelate.Component(None)
    component.shaid = component_id
    component.populate_from_uri(fuseki_process)
    shaid = component.shaid
    #form = forms.ComponentMetadata(initial=component.__dict__)
    con_dict = {'component':component, 'shaid':shaid}#, 'form':form}
    context = RequestContext(request, con_dict)
    response = render_to_response('viewcomponent.html', context)
    return response



def invalid_mappings(request):
    """
    list mappings which reference the concept search criteria
    by concept by source then target
    
    """
    requestor_path = request.GET.get('ref', '')
    requestor_path = urllib.unquote(requestor_path).decode('utf8')
    if requestor_path == '':
        requestor_path = '{}'
    requestor = json.loads(requestor_path)
    invalids = []
    for key, inv_mappings in requestor.iteritems():
        invalid = {'label':key, 'mappings':[]}
        for inv_map in inv_mappings:
            muri = inv_map['amap']
            mapping = metarelate.Mapping(muri)
            url = reverse('mapping', kwargs={'mapping_id':mapping.shaid})
            sig = inv_map.get('signature', [])
            label = []
            if isinstance(sig, list):
                for elem in sig:
                    label.append(elem.split('/')[-1].strip('<>'))
            else:
                label.append(sig.split('/')[-1].strip('<>'))
            if label:
                '&'.join(label)
            else:
                label = 'mapping'
            invalid['mappings'].append({'url':url, 'label':label})
        invalids.append(invalid)
    context_dict = {'invalid': invalids}
    context = RequestContext(request, context_dict)
    return render_to_response('select_list.html', context)


### searching    
        
def search(request):
    """
    to search for a mapping with any of the provided statements
    """
    SearchFormset = formset_factory(forms.SearchStatement)
    if request.method == 'POST':
        formset = SearchFormset(request.POST)
        if formset.is_valid():
            statements = []
            for sform in formset.cleaned_data:
                predicate = sform.get('predicate')
                rdfobject = sform.get('rdfobject')
                statements.append({'predicate':predicate, 
                                   'rdfobject':rdfobject})
            sresults = fuseki_process.search(statements)
            url = url_qstr(reverse('invalid_mappings'), 
                           ref=json.dumps(sresults))
            return HttpResponseRedirect(url)
    else:
        formset = SearchFormset()
    con_dict = {'formset':formset}
    context = RequestContext(request, con_dict)
    response = render_to_response('searchform.html', context)
    return response
        


def review(request):
    """
    returns a view of a list of mapping links
    which are different from upstream/master

    """
    if metarelate.site_config.get('static_dir'):
        cwd = os.path.join(metarelate.site_config.get('static_dir'),
                           'metarelate.net')
    data = subprocess.check_output(['git', 'diff', 'upstream/master',
                                    'mappings.ttl'],
                                    cwd=cwd,
                                    stderr=subprocess.STDOUT)

    pattern = re.compile('http://metarelate.net/metOcean/mapping/*')

    pattern1 = re.compile(r'\+<http://www.metarelate.net/metOcean/mapping/(?P<map_sha>\w+)>')
    pattern2 = re.compile(r'\+map:(?P<map_sha>\w+)')

    datalines = data.split('\n')

    map_ids = []
    map_str = '<http://www.metarelate.net/metOcean/mapping/{}>'

    for line in datalines:
        m1 = pattern1.match(line)
        m2 = pattern2.match(line)
        if m1:
            map_ids.append(map_str.format(m1.group(1)))
        elif m2:
            map_ids.append(map_str.format(m2.group(1)))
    label = 'Mappings in this branch but not on upstream master'
    con_dict = _process_mapping_list(map_ids, label)
    context = RequestContext(request, con_dict)
    response = render_to_response('select_list.html', context)
    return response

def add_contact(request):
    """
    returns a form to add a new contact
    """
    if request.method == 'POST':
        form = forms.ContactForm(request.POST)
        if form.is_valid():
            new_contact = {}
            if form.cleaned_data.get('name'):
                new_contact['skos:prefLabel'] = '"{}"'.format(form.cleaned_data['name'])
            if form.cleaned_data.get('github_id'):
                ghid = 'github:{}'.format(form.cleaned_data['github_id'])
                new_contact['skos:definition'] =  ghid
            if form.cleaned_data.get('scheme'):
                new_contact['skos:inScheme'] = '<{}>'.format(form.cleaned_data['scheme'])
            globalDateTime = datetime.datetime.now().isoformat()
            new_contact['dc:valid'] = '"%s"^^xsd:dateTime' % globalDateTime
            qstr, instr = metarelate.Contact.sparql_creator(new_contact)
            contact = fuseki_process.create(qstr, instr)
            rstr = '<script type="text/javascript">window.close()</script>'
            reload(forms)
            return HttpResponse(rstr)
    else:
        form = forms.ContactForm()
        con_dict = {'form':form}
        context = RequestContext(request, con_dict)
        response = render_to_response('simpleform.html', context)
    return response

def newmapping(request):
    PForm = forms.ConceptProperty
    CFormset = formset_factory(PForm, formset=forms.Concept)
    if request.method == 'POST':
        # create a form instance and populate it with data from the request:
        sourceformset = CFormset(request.POST, prefix='source')
        targetformset = CFormset(request.POST, prefix='target')
        # check whether it's valid:
        if sourceformset.is_valid() and targetformset.is_valid():
            # process the data in form.cleaned_data as required
            # ...
            # redirect to a new URL:
            return HttpResponseRedirect('/thanks/')

    # if a GET (or any other method) we'll create a blank form
    else:
        sourceformset = CFormset(prefix='source')
        targetformset = CFormset(prefix='target')
        # ff = formset_factory(forms.TestConceptProperty, formset=forms.Concept)
        # targetformset = ff(prefix='target')
        context = RequestContext(request, {'sourceformset': sourceformset,
                                           'targetformset': targetformset})

    return render_to_response('newmapping.html', context)


def anewmapping(request):
    # PForm = forms.ConceptProperty
    # CFormset = formset_factory(PForm)#, formset=forms.Concept)

    if request.method == 'POST':
        # source = CFormset(request.POST, prefix='source')
        # target = CFormset(request.POST, prefix='target')

        source = forms.Concept(request.POST, prefix='source')
        target = forms.Concept(request.POST, prefix='target')
        if source.is_valid() and target.is_valid():
            return render_to_response('anewmapping.html', context)
    else:
        source = forms.Concept(prefix='source')
        target = forms.Concept(prefix='target')
        # source = CFormset(prefix='source')
        # target = CFormset(prefix='target')

        context = RequestContext(request, {'source': source,
                                           'target': target})
    return render_to_response('anewmapping.html', context)



def _process_mapping_list(map_ids, label):
    mapurls = {'label': label,
               'mappings':[]}
    for amap in map_ids:
        qstr = metarelate.Mapping.sparql_retriever(amap)
        mapping = fuseki_process.retrieve(qstr)
        if mapping is not None:
            sm = fuseki_process.structured_mapping(mapping)
            referrer = sm.json_referrer()
            map_json = json.dumps(referrer)
            url = url_qstr(reverse('mapping_edit'), ref=map_json)
            label = 'mapping'
            label = '{source} -> {target} mapping'
            label = label.format(source=sm.source.scheme.notation,
                                 target=sm.target.scheme.notation)
            if isinstance(sm.source.components[0], metarelate.PropertyComponent):
                sps = ''
                for prop in sm.source.components[0].values():
                    pname = prop.name.notation
                    pval = ''
                    # if hasattr(prop, 'value'):
                    if prop.value:
                        pval = prop.value.notation
                    sps += '{pn}:{pv}; '.format(pn=pname, pv=pval)
                label += '({})'.format(sps)
            mapurls['mappings'].append({'url':url, 'label':label})
    context_dict = {'invalid': [mapurls]}  
    return context_dict
