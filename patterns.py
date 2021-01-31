from .settings import adsorbate_elements, site_heights  
from .settings import monodentate_adsorbate_list, multidentate_adsorbate_list
from .adsorption_sites import ClusterAdsorptionSites, SlabAdsorptionSites
from .adsorption_sites import group_sites_by_surface
from .adsorbate_coverage import ClusterAdsorbateCoverage, SlabAdsorbateCoverage
from .utilities import is_list_or_tuple, get_mic, atoms_too_close_after_addition 
from .labels import get_cluster_signature_from_label, get_slab_signature_from_label
from .actions import add_adsorbate_to_site, remove_adsorbate_from_site 
from ase.io import read, write, Trajectory
from ase.formula import Formula
from copy import deepcopy
import networkx.algorithms.isomorphism as iso
import networkx as nx
import numpy as np
import warnings
import random


class StochasticPatternGenerator(object):

    def __init__(self, images,                                                       
                 adsorbate_species,
                 image_probabilities=None,
                 species_probabilities=None,
                 min_adsorbate_distance=1.5,
                 adsorption_sites=None,
                 surface=None,
                 heights=site_heights,
                 allow_6fold=False,
                 composition_effect=True,
                 dmax=2.5,
                 unique=True,
                 species_forbidden_sites=None,    
                 species_forbidden_labels=None,
                 fragmentation=True,
                 trajectory='patterns.traj',
                 append_trajectory=False,
                 logfile='patterns.log'):
        """
        image_probabilities: list
        species_probabilities: dictionary 
        adsorption_sites: should only provide when the surface composition is fixed
        unique: whether discard duplicates based on isomorphism or not
        species_forbidden_sites: dictionary with species key and forbidden site (list) values 
        append_trajecotry: if unique=True, also check for isomorphism for existing structures in the trajectory.

        if you want to do stochastic pattern generation but for all images systematically, do
        >>> for atoms in images:
        >>>     SPG = StochasticPatternGenerator(atoms, ..., append_trajectory=True)
        >>>     SPG.run(ngen = 10)
        """

        self.images = images if is_list_or_tuple(images) else [images]                     
        self.adsorbate_species = adsorbate_species if is_list_or_tuple(
                                 adsorbate_species) else [adsorbate_species]
        self.monodentate_adsorbates = [s for s in adsorbate_species if s in 
                                       monodentate_adsorbate_list]
        self.multidentate_adsorbates = [s for s in adsorbate_species if s in
                                        multidentate_adsorbate_list]
        if len(self.adsorbate_species) != len(self.monodentate_adsorbates +
        self.multidentate_adsorbates):
            diff = list(set(self.adsorbate_species) - 
                        set(self.monodentate_adsorbates +
                            self.multidentate_adsorbates))
            raise ValueError('Species {} are not defined '.format(diff) +
                             'in adsorbate_list in settings.py')             

        self.image_probabilities = image_probabilities
        if self.image_probabilities is not None:
            assert len(self.image_probabilities) == len(self.images)
        self.species_probabilities = species_probabilities
        if self.species_probabilities is not None:
            assert len(self.species_probabilities.keys()) == len(self.adsorbate_species)
            self.species_probability_list = [self.species_probabilities[a] for 
                                             a in self.adsorbate_species]               
         
        self.min_adsorbate_distance = min_adsorbate_distance
        self.adsorption_sites = adsorption_sites
        self.surface = surface
        self.heights = heights
        self.dmax = dmax
        self.unique = unique
        self.species_forbidden_sites = species_forbidden_sites
        self.species_forbidden_labels = species_forbidden_labels

        if self.species_forbidden_labels is not None:
            self.species_forbidden_labels = {k: v if is_list_or_tuple(v) else [v] for
                                             k, v in self.species_forbidden_labels.items()}
        if self.species_forbidden_sites is not None:
            self.species_forbidden_sites = {k: v if is_list_or_tuple(v) else [v] for
                                            k, v in self.species_forbidden_sites.items()}  
        self.fragmentation = fragmentation
        self.append_trajectory = append_trajectory
        if isinstance(trajectory, str):            
            self.traj_name = trajectory 
            self.trajectory = Trajectory(trajectory, mode='a') if self.append_trajectory \
                              else Trajectory(trajectory, mode='w')                        
        if isinstance(logfile, str):
            self.logfile = open(logfile, 'a')      
 
        if self.adsorption_sites is not None:
            if self.multidentate_adsorbates:
                self.bidentate_nblist = \
                self.adsorption_sites.get_neighbor_site_list(neighbor_number=1)
            self.site_nblist = \
            self.adsorption_sites.get_neighbor_site_list(neighbor_number=2)
            self.allow_6fold = self.adsorption_sites.allow_6fold
            self.composition_effect = self.adsorption_sites.composition_effect
        else:
            self.allow_6fold = allow_6fold
            self.composition_effect = composition_effect

    def _add_adsorbate(self, adsorption_sites):
        sas = adsorption_sites
        if self.adsorption_sites is not None:                               
            site_nblist = self.site_nblist
        else:
            site_nblist = sas.get_neighbor_site_list(neighbor_number=2)     
         
        if self.clean_slab:
            hsl = sas.site_list
            nbstids = set()
            neighbor_site_indices = []
        else:
            if True in self.atoms.pbc:
                sac = SlabAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                            label_occupied_sites=self.unique) 
            else: 
                sac = ClusterAdsorbateCoverage(self.atoms, sas, dmax=self.dmax, 
                                               label_occupied_sites=self.unique)                                                
            hsl = sac.hetero_site_list
            nbstids, selfids = [], []
            for j, st in enumerate(hsl):
                if st['occupied']:
                    nbstids += site_nblist[j]
                    selfids.append(j)
            nbstids = set(nbstids)
            neighbor_site_indices = [v for v in nbstids if v not in selfids]            
                                                                                             
        # Select adsorbate with probablity 
        if not self.species_probabilities:
            adsorbate = random.choice(self.adsorbate_species)
        else: 
            adsorbate = random.choices(k=1, population=self.adsorbate_species,
                                       probabilities=self.species_probability_list)[0]    
                                                                                             
        # Only add one adsorabte to a site at least 2 shells 
        # away from currently occupied sites
        nsids = [i for i, s in enumerate(hsl) if i not in nbstids]

        if self.species_forbidden_labels is not None:
            if adsorbate in self.species_forbidden_labels:
                labs = self.species_forbidden_labels[adsorbate]
                if True in self.atoms.pbc:
                    def get_signature(site):
                        if sas.composition_effect:
                            signature = [site['site'], site['geometry'], site['composition']]
                        else:
                            signature = [site['site'], site['geometry']]
                        return sas.label_dict['|'.join(signature)]                        

                    forb_signatures = [get_slab_signature_from_label(lab, sas.surface,
                                       sas.composition_effect, sas.metals) for lab in labs]    
                else:
                    def get_signature(site):
                        if sas.composition_effect:
                            signature = [site['site'], site['surface'], site['composition']]
                        else:
                            signature = [site['site'], site['surface']]
                        return sas.label_dict['|'.join(signature)]                   

                    forb_signatures = [get_cluster_signature_from_label(lab, 
                                       sas.composition_effect, sas.metals) for lab in labs] 
                
                nsids = [i for i in nsids if get_signature(hsl[i]) not in forb_signatures]    

        elif self.species_forbidden_sites is not None:
            if adsorbate in self.species_forbidden_sites:
                nsids = [i for i in nsids if hsl[i]['site'] not in 
                         self.species_forbidden_sites[adsorbate]] 
        if not nsids:                                                             
            if self.logfile is not None:                                          
                self.logfile.write('Not enough space to add {} '.format(adsorbate)
                                   + 'to any site. Addition failed!\n')
                self.logfile.flush()
            return
                                                                                             
        # Prohibit adsorbates with more than 1 atom from entering subsurf 6-fold sites
        subsurf_site = True
        nsi = None
        while subsurf_site: 
            nsi = random.choice(nsids)
            if self.allow_6fold:
                subsurf_site = (len(adsorbate) > 1 and hsl[nsi]['site'] == '6fold')
            else:
                subsurf_site = (hsl[nsi]['site'] == '6fold')
                                                                                             
        nst = hsl[nsi]            
        if adsorbate in self.multidentate_adsorbates:                                                   
            if self.adsorption_sites is not None:                               
                bidentate_nblist = self.bidentate_nblist
            else:
                bidentate_nblist = sas.get_neighbor_site_list(neighbor_number=1)

            binbs = bidentate_nblist[nsi]                    
            binbids = [n for n in binbs if n not in nbstids]
            if not binbids and nst['site'] != '6fold':
                if self.logfile is not None:                                          
                    self.logfile.write('Not enough space to add {} '.format(adsorbate) 
                                       + 'to any site. Addition failed!\n')
                    self.logfile.flush()
                return            
                                                                                             
            # Rotate a bidentate adsorbate to the direction of a randomly 
            # choosed neighbor site
            nbst = hsl[random.choice(binbids)]
            pos = nst['position'] 
            nbpos = nbst['position'] 
            orientation = get_mic(nbpos, pos, self.atoms.cell)
            add_adsorbate_to_site(self.atoms, adsorbate, nst, 
                                  height=self.heights[nst['site']],
                                  orientation=orientation)                                 
        else:
            add_adsorbate_to_site(self.atoms, adsorbate, nst, 
                                  height=self.heights[nst['site']])                            

        if True in self.atoms.pbc:
            nsac = SlabAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                         label_occupied_sites=self.unique) 
        else:
            nsac = ClusterAdsorbateCoverage(self.atoms, sas, dmax=self.dmax, 
                                            label_occupied_sites=self.unique)
        nhsl = nsac.hetero_site_list
                                                                           
        # Make sure there no new site too close to previous sites after 
        # the action. Useful when adding large molecules
        if any(s for i, s in enumerate(nhsl) if (s['occupied'])
        and (i in neighbor_site_indices)):
            if self.logfile is not None:
                self.logfile.write('The added {} is too close '.format(adsorbate)
                                   + 'to another adsorbate. Addition failed!\n')
                self.logfile.flush()
            return
        ads_atoms = self.atoms[[a.index for a in self.atoms if                   
                                a.symbol in adsorbate_elements]]
        if atoms_too_close_after_addition(ads_atoms, len(list(Formula(adsorbate))), 
        self.min_adsorbate_distance, mic=(True in self.atoms.pbc)):        
            if self.logfile is not None:
                self.logfile.write('The added {} is too close '.format(adsorbate)
                                   + 'to another adsorbate. Addition failed!\n')
                self.logfile.flush()
            return

        return nsac                                                                

    def _remove_adsorbate(self, adsorption_sites):
        sas = adsorption_sites 
        if True in self.atoms.pbc:                    
            sac = SlabAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                        label_occupied_sites=self.unique) 
        else: 
            sac = ClusterAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                           label_occupied_sites=self.unique)
        hsl = sac.hetero_site_list
        occupied = [s for s in hsl if s['occupied']]
        if not occupied:
            if self.logfile is not None:
                self.logfile.write('There is no occupied site. Removal failed!\n')
                self.logfile.flush()
            return
        rmst = random.choice(occupied)
        remove_adsorbate_from_site(self.atoms, rmst)

        ads_remain = [a for a in self.atoms if a.symbol in adsorbate_elements]
        if not ads_remain:
            if self.logfile is not None:
                self.logfile.write('Last adsorbate has been removed ' + 
                                   'from image {}\n'.format(self.n_image))
                self.logfile.flush()
            return

        if True in self.atoms.pbc:
            nsac = SlabAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                         label_occupied_sites=self.unique) 
            nsac = ClusterAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                            label_occupied_sites=self.unique)                      
        return nsac 

    def _move_adsorbate(self, adsorption_sites):           
        sas = adsorption_sites
        if self.adsorption_sites is not None:
            site_nblist = self.site_nblist
        else:
            site_nblist = sas.get_neighbor_site_list(neighbor_number=2) 

        if True in self.atoms.pbc:                                                                         
            sac = SlabAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                        label_occupied_sites=self.unique) 
        else: 
            sac = ClusterAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                           label_occupied_sites=self.unique)
        hsl = sac.hetero_site_list
        occupied = [s for s in hsl if s['occupied']]                         
        if not occupied:
            if self.logfile is not None:
                self.logfile.write('There is no occupied site. Move failed!\n')
                self.logfile.flush()
            return
        rmst = random.choice(occupied)
        adsorbate = rmst['adsorbate']
        remove_adsorbate_from_site(self.atoms, rmst)

        nbstids, selfids = [], []
        for j, st in enumerate(hsl):
            if st['occupied']:
                nbstids += site_nblist[j]
                selfids.append(j)
        nbstids = set(nbstids)
        neighbor_site_indices = [v for v in nbstids if v not in selfids]
                                                                                        
        # Only add one adsorabte to a site at least 2 shells 
        # away from currently occupied sites
        nsids = [i for i, s in enumerate(hsl) if i not in nbstids]

        if self.species_forbidden_labels is not None:
            if adsorbate in self.species_forbidden_labels:
                labs = self.species_forbidden_labels[adsorbate]
                if True in self.atoms.pbc:
                    def get_signature(site):
                        if sas.composition_effect:
                            signature = [site['site'], site['geometry'], site['composition']]
                        else:
                            signature = [site['site'], site['geometry']]
                        return sas.label_dict['|'.join(signature)]                        
                                                                                             
                    forb_signatures = [get_slab_signature_from_label(lab, sas.surface,
                                       sas.composition_effect, sas.metals) for lab in labs]  
                else:
                    def get_signature(site):
                        if sas.composition_effect:
                            signature = [site['site'], site['surface'], site['composition']]
                        else:
                            signature = [site['site'], site['surface']]
                        return sas.label_dict['|'.join(signature)]                   
                                                                                             
                    forb_signatures = [get_cluster_signature_from_label(lab, 
                                       sas.composition_effect, sas.metals) for lab in labs]
                
                nsids = [i for i in nsids if get_signature(hsl[i]) not in forb_signatures]   

        elif self.species_forbidden_sites is not None:
            if adsorbate in self.species_forbidden_sites:
                nsids = [i for i in nsids if hsl[i]['site'] not in 
                         self.species_forbidden_sites[adsorbate]] 
        if not nsids:                                                             
            if self.logfile is not None:                                          
                self.logfile.write('Not enough space to place {} '.format(adsorbate)
                                   + 'on any other site. Move failed!\n')
                self.logfile.flush()
            return
                                                                                        
        # Prohibit adsorbates with more than 1 atom from entering subsurf 6-fold sites
        subsurf_site = True
        nsi = None
        while subsurf_site: 
            nsi = random.choice(nsids)
            if self.allow_6fold:
                subsurf_site = (len(adsorbate) > 1 and hsl[nsi]['site'] == '6fold')
            else:
                subsurf_site = (hsl[nsi]['site'] == '6fold')
                                                                                        
        nst = hsl[nsi]            
        if adsorbate in self.multidentate_adsorbates:                                   
            if self.adsorption_sites is not None:
                bidentate_nblist = self.bidentate_nblist
            else:
                bidentate_nblist = sas.get_neighbor_site_list(neighbor_number=1)

            binbs = bidentate_nblist[nsi]                    
            binbids = [n for n in binbs if n not in nbstids]
            if not binbids:
                if self.logfile is not None:
                    self.logfile.write('Not enough space to place {} '.format(adsorbate) 
                                       + 'on any other site. Move failed!\n')
                    self.logfile.flush()
                return
                                                                                        
            # Rotate a bidentate adsorbate to the direction of a randomly 
            # choosed neighbor site
            nbst = hsl[random.choice(binbids)]
            pos = nst['position'] 
            nbpos = nbst['position'] 
            orientation = get_mic(nbpos, pos, self.atoms.cell)
            add_adsorbate_to_site(self.atoms, adsorbate, nst, 
                                  height=self.heights[nst['site']], 
                                  orientation=orientation)    
        else:
            add_adsorbate_to_site(self.atoms, adsorbate, nst,
                                  height=self.heights[nst['site']])                          

        if True in self.atoms.pbc:
            nsac = SlabAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                         label_occupied_sites=self.unique) 
        else: 
            nsac = ClusterAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                            label_occupied_sites=self.unique)
        nhsl = nsac.hetero_site_list
                                                                           
        # Make sure there no new site too close to previous sites after 
        # the action. Useful when adding large molecules
        if any(s for i, s in enumerate(nhsl) if s['occupied'] and (i in 
        neighbor_site_indices)):
            if self.logfile is not None:
                self.logfile.write('The new position of {} is too '.format(adsorbate)
                                   + 'close to another adsorbate. Move failed!\n')
                self.logfile.flush()
            return
        ads_atoms = self.atoms[[a.index for a in self.atoms if                   
                                a.symbol in adsorbate_elements]]
        if atoms_too_close_after_addition(ads_atoms, len(list(Formula(adsorbate))), 
        self.min_adsorbate_distance, mic=(True in self.atoms.pbc)):
            if self.logfile is not None:
                self.logfile.write('The new position of {} is too '.format(adsorbate)
                                   + 'close to another adsorbate. Move failed!\n')
                self.logfile.flush()
            return
 
        return nsac                                                                 

    def _replace_adsorbate(self, adsorption_sites):
        sas = adsorption_sites                     
        if True in self.atoms.pbc:                                      
            sac = SlabAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                        label_occupied_sites=self.unique) 
        else: 
            sac = ClusterAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                           label_occupied_sites=self.unique)
        hsl = sac.hetero_site_list
        occupied_stids = [i for i in range(len(hsl)) if hsl[i]['occupied']]
        if not occupied_stids:
            if self.logfile is not None:
                self.logfile.write('There is no occupied site. Replacement failed!\n')
                self.logfile.flush()
            return

        rpsti = random.choice(occupied_stids)
        rpst = hsl[rpsti]
        remove_adsorbate_from_site(self.atoms, rpst)

        # Select a different adsorbate with probablity 
        old_adsorbate = rpst['adsorbate']
        new_options = [a for a in self.adsorbate_species if a != old_adsorbate]

        if self.species_forbidden_labels is not None:
            _new_options = []
            for o in new_options:
                if o in self.species_forbidden_labels: 
                    if True in self.atoms.pbc:
                        if sas.composition_effect:
                            signature = [rpst['site'], rpst['geometry'], rpst['composition']]
                        else:
                            signature = [rpst['site'], rpst['geometry']]
                        lab = sas.label_dict['|'.join(signature)]                        
                                                                                                 
                    else:
                        if sas.composition_effect:
                            signature = [rpst['site'], rpst['surface'], rpst['composition']]
                        else:
                            signature = [rpst['site'], rpst['surface']]
                        lab = sas.label_dict['|'.join(signature)]                                                                                            
                    if lab not in self.species_forbidden_labels[o]:
                        _new_options.append(o)
            new_options = _new_options                                                       

        elif self.species_forbidden_sites is not None:                      
            _new_options = []
            for o in new_options: 
                if o in self.species_forbidden_sites:
                    if rpst['site'] not in self.species_forbidden_sites[o]:
                        _new_options.append(o)
            new_options = _new_options

        # Prohibit adsorbates with more than 1 atom from entering subsurf 6-fold sites
        if self.allow_6fold and rpst['site'] == '6fold':
            new_options = [o for o in new_options if len(o) == 1]

        if not self.species_probabilities:
            adsorbate = random.choice(new_options)
        else:
            new_probabilities = [self.species_probabilities[a] for a in new_options]
            adsorbate = random.choices(k=1, population=self.adsorbate_species,
                                       probabilities=new_probabilities)[0] 
        if self.adsorption_sites is not None:
            site_nblist = self.site_nblist
        else:
            site_nblist = sas.get_neighbor_site_list(neighbor_number=2)

        nbstids, selfids = [], []
        for j, st in enumerate(hsl):
            if st['occupied']:
                nbstids += site_nblist[j]
                selfids.append(j)
        nbstids = set(nbstids)
        neighbor_site_indices = [v for v in nbstids if v not in selfids]

        if adsorbate in self.multidentate_adsorbates:
            if self.adsorption_sites is not None:                                      
                bidentate_nblist = self.bidentate_nblist
            else:
                bidentate_nblist = sas.get_neighbor_site_list(neighbor_number=1)
            
            binbs = bidentate_nblist[rpsti]                    
            binbids = [n for n in binbs if n not in nbstids]
            if not binbids:
                if self.logfile is not None:
                    self.logfile.write('Not enough space to add {} '.format(adsorbate)  
                                       + 'to any site. Replacement failed!\n')
                    self.logfile.flush()
                return
                                                                                            
            # Rotate a bidentate adsorbate to the direction of a randomly 
            # choosed neighbor site
            nbst = hsl[random.choice(binbids)]
            pos = rpst['position'] 
            nbpos = nbst['position'] 
            orientation = get_mic(nbpos, pos, self.atoms.cell)
            add_adsorbate_to_site(self.atoms, adsorbate, rpst, 
                                  height=self.heights[rpst['site']],
                                  orientation=orientation)                     
        else:
            add_adsorbate_to_site(self.atoms, adsorbate, rpst,
                                  height=self.heights[rpst['site']])                 
 
        if True in self.atoms.pbc:   
            nsac = SlabAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                         label_occupied_sites=self.unique) 
        else: 
            nsac = ClusterAdsorbateCoverage(self.atoms, sas, dmax=self.dmax,
                                            label_occupied_sites=self.unique)         
        nhsl = nsac.hetero_site_list                            
                                                                           
        # Make sure there no new site too close to previous sites after 
        # the action. Useful when adding large molecules
        if any(s for i, s in enumerate(nhsl) if s['occupied'] and (i in 
        neighbor_site_indices)):
            if self.logfile is not None:
                self.logfile.write('The added {} is too close '.format(adsorbate)
                                   + 'to another adsorbate. Replacement failed!\n')
                self.logfile.flush()
            return
        ads_atoms = self.atoms[[a.index for a in self.atoms if                   
                                a.symbol in adsorbate_elements]]
        if atoms_too_close_after_addition(ads_atoms, len(list(Formula(adsorbate))), 
        self.min_adsorbate_distance, mic=(True in self.atoms.pbc)):
            if self.logfile is not None:
                self.logfile.write('The added {} is too close '.format(adsorbate)
                                   + 'to another adsorbate. Replacement failed!\n')
                self.logfile.flush()
            return

        return nsac                        
 
    def run(self, n_gen, 
            actions=['add','remove','replace'], 
            action_probabilities=None):
        
        actions = actions if is_list_or_tuple(actions) else [actions]
        if action_probabilities is not None:
            all_action_probabilities = [action_probabilities[a] for a in actions]
        
        self.labels_list, self.graph_list = [], []

        if self.unique and self.append_trajectory:                                 
            if self.logfile is not None:                             
                self.logfile.write('Loading graphs for existing structures in ' +
                                   '{}. This might take a while.\n'.format(self.traj_name))
                self.logfile.flush()

            prev_images = read(self.traj_name, index=':')
            for patoms in prev_images:
                if self.adsorption_sites is not None:
                    psas = self.adsorption_sites
                elif True in patoms.pbc:
                    if self.surface is None:
                        raise ValueError('Please specify the surface type')
                    psas = SlabAdsorptionSites(patoms, self.surface,
                                               self.allow_6fold,
                                               self.composition_effect)
                else:
                    psas = ClusterAdsorptionSites(patoms, self.allow_6fold,
                                                  self.composition_effect) 
                if True in patoms.pbc:
                    psac = SlabAdsorbateCoverage(patoms, psas, dmax=self.dmax,
                                                 label_occupied_sites=self.unique)           
                else:
                    psac = ClusterAdsorbateCoverage(patoms, psas, dmax=self.dmax,
                                                    label_occupied_sites=self.unique)        

                plabs = psac.get_occupied_labels(fragmentation=self.fragmentation)
                pG = psac.get_graph(fragmentation=self.fragmentation)
                self.labels_list.append(plabs)
                self.graph_list.append(pG)

        n_new = 0
        n_old = 0
        # Start the iteration
        while n_new < n_gen:
            if n_old == n_new:
                if self.logfile is not None:                                    
                    self.logfile.write('Generating pattern {}\n'.format(n_new))
                    self.logfile.flush()
                n_old += 1
            # Select image with probablity 
            if not self.species_probabilities:
                self.atoms = random.choice(self.images).copy()
            else: 
                self.atoms = random.choices(k=1, population=self.images, 
                                            probabilities=self.image_probabilities)[0].copy()
            self.n_image = n_new 
            if self.adsorption_sites is not None:
                sas = self.adsorption_sites
            elif True in self.atoms.pbc:
                if self.surface is None:
                    raise ValueError('Please specify the surface type')
                sas = SlabAdsorptionSites(self.atoms, self.surface,
                                          self.allow_6fold,
                                          self.composition_effect)
            else:
                sas = ClusterAdsorptionSites(self.atoms, self.allow_6fold,
                                             self.composition_effect)      
            # Choose an action 
            self.clean_slab = False
            nslab = len(sas.indices) 
            if nslab == len(self.atoms):
                if 'add' not in actions:                                                             
                    warnings.warn("There is no adsorbate in image {}. ".format(n_new)
                                  + "The only available action is 'add'")
                    continue 
                else:
                    action = 'add'
                    self.clean_slab = True
            else:
                if not action_probabilities:
                    action = random.choice(actions)
                else:
                    assert len(action_probabilities.keys()) == len(actions)
                    action = random.choices(k=1, population=actions, 
                                            probabilities=all_action_probabilities)[0] 
            if self.logfile is not None:                                    
                self.logfile.write('Action: {}\n'.format(action))
                self.logfile.flush()

            if action == 'add':             
                nsac = self._add_adsorbate(sas)
            elif action == 'remove':
                nsac = self._remove_adsorbate(sas)
            elif action == 'move':
                nsac = self._move_adsorbate(sas)
            elif action == 'replace':
                nsac = self._replace_adsorbate(sas)
            if not nsac:
                continue

            labs = nsac.get_occupied_labels(fragmentation=self.fragmentation)
            if self.unique:
                G = nsac.get_graph(fragmentation=self.fragmentation)
                if labs in self.labels_list: 
                    if self.graph_list:
                        # Skip duplicates based on isomorphism 
                        nm = iso.categorical_node_match('symbol', 'X')
                        potential_graphs = [g for i, g in enumerate(self.graph_list) 
                                            if self.labels_list[i] == labs]
                        if self.clean_slab and potential_graphs:
                            if self.logfile is not None:                              
                                self.logfile.write('Duplicate found by label match. '
                                                   + 'Discarded!\n')
                                self.logfile.flush()
                            continue
                        if any(H for H in potential_graphs if 
                        nx.isomorphism.is_isomorphic(G, H, node_match=nm)):
                            if self.logfile is not None:                             
                                self.logfile.write('Duplicate found by isomorphism. '
                                                   + 'Discarded!\n')
                                self.logfile.flush()
                            continue            
                self.labels_list.append(labs)
                self.graph_list.append(G)

            if self.logfile is not None:
                self.logfile.write('Succeed! Pattern generated: {}\n\n'.format(labs))
                self.logfile.flush()
            if 'data' not in self.atoms.info:
                 self.atoms.info['data'] = {}
            self.atoms.info['data']['labels'] = labs
            self.trajectory.write(self.atoms)
            n_new += 1


class SystematicPatternGenerator(object):

    def __init__(self, images,                                                     
                 adsorbate_species,
                 min_adsorbate_distance=1.5,
                 adsorption_sites=None,
                 surface=None,
                 heights=site_heights,
                 allow_6fold=False,
                 composition_effect=True,
                 dmax=2.5,
                 unique=True,
                 species_forbidden_sites=None,
                 species_forbidden_labels=None,
                 enumerate_orientations=True,
                 trajectory='patterns.traj',
                 append_trajectory=False,
                 logfile='patterns.log'):

        """
       enumerate_orientations: whether to enumerate all orientations of multidentate species
       """

        self.images = images if is_list_or_tuple(images) else [images]                     
        self.adsorbate_species = adsorbate_species if is_list_or_tuple(
                                 adsorbate_species) else [adsorbate_species]
        self.monodentate_adsorbates = [s for s in adsorbate_species if s in 
                                       monodentate_adsorbate_list]
        self.multidentate_adsorbates = [s for s in adsorbate_species if s in
                                        multidentate_adsorbate_list]
        if len(self.adsorbate_species) != len(self.monodentate_adsorbates +
        self.multidentate_adsorbates):
            diff = list(set(self.adsorbate_species) - 
                        set(self.monodentate_adsorbates +
                            self.multidentate_adsorbates))
            raise ValueError('Species {} is not defined '.format(diff) +
                             'in adsorbate_list in settings.py')             

        self.min_adsorbate_distance = min_adsorbate_distance
        self.adsorption_sites = adsorption_sites
        self.surface = surface
        self.heights = heights        
        self.dmax = dmax
        self.unique = unique
        self.species_forbidden_sites = species_forbidden_sites
        self.species_forbidden_labels = species_forbidden_labels
                                                                                           
        if self.species_forbidden_labels is not None:
            self.species_forbidden_labels = {k: v if is_list_or_tuple(v) else [v] for
                                             k, v in self.species_forbidden_labels.items()}
        if self.species_forbidden_sites is not None:
            self.species_forbidden_sites = {k: v if is_list_or_tuple(v) else [v] for
                                            k, v in self.species_forbidden_sites.items()}
        self.enumerate_orientations = enumerate_orientations
        self.append_trajectory = append_trajectory
        if isinstance(trajectory, str):
            self.traj_name = trajectory            
            self.trajectory = Trajectory(trajectory, mode='a') if self.append_trajectory \
                              else Trajectory(trajectory, mode='w')                       
        if isinstance(logfile, str):
            self.logfile = open(logfile, 'a')                 
 
        if self.adsorption_sites is not None:
            if self.multidentate_adsorbates:
                self.bidentate_nblist = \
                self.adsorption_sites.get_neighbor_site_list(neighbor_number=1)
            self.site_nblist = \
            self.adsorption_sites.get_neighbor_site_list(neighbor_number=2)
            self.allow_6fold = self.adsorption_sites.allow_6fold
            self.composition_effect = self.adsorption_sites.composition_effect
        else:
            self.allow_6fold = allow_6fold
            self.composition_effect = composition_effect

    def _add_adsorbate(self, adsorption_sites):
        self.n_duplicate = 0
        sas = adsorption_sites
        if self.adsorption_sites is not None:                                         
            site_nblist = self.site_nblist
        else:
            site_nblist = sas.get_neighbor_site_list(neighbor_number=2) 
       
        # Take care of clean surface slab
        if self.clean_slab:
            hsl = sas.site_list
            nbstids = set()    
            neighbor_site_indices = []        
        else:
            if True in self.image.pbc: 
                sac = SlabAdsorbateCoverage(self.image, sas, dmax=self.dmax,
                                            label_occupied_sites=self.unique) 
            else: 
                sac = ClusterAdsorbateCoverage(self.image, sas, dmax=self.dmax,
                                               label_occupied_sites=self.unique)
            hsl = sac.hetero_site_list
            nbstids, selfids = [], []
            for j, st in enumerate(hsl):
                if st['occupied']:
                    nbstids += site_nblist[j]
                    selfids.append(j)
            nbstids = set(nbstids)
            neighbor_site_indices = [v for v in nbstids if v not in selfids]

        if self.multidentate_adsorbates:
            if self.adsorption_sites is not None:
                bidentate_nblist = self.bidentate_nblist
            else:
                bidentate_nblist = sas.get_neighbor_site_list(neighbor_number=1)

        # Only add one adsorabte to a site at least 2 shells away from
        # currently occupied sites
        newsites, binbids = [], []
        for i, s in enumerate(hsl):
            if i not in nbstids:
                if self.multidentate_adsorbates:
                    binbs = bidentate_nblist[i]
                    binbis = [n for n in binbs if n not in nbstids]
                    if not binbis and s['site'] != '6fold':
                        continue 
                    binbids.append(binbis)
                newsites.append(s)

        for k, nst in enumerate(newsites):
            for adsorbate in self.adsorbate_species:
                if self.species_forbidden_labels is not None:
                    if adsorbate in self.species_forbidden_labels: 
                        if True in self.image.pbc:
                            if sas.composition_effect:
                                signature = [nst['site'], nst['geometry'], nst['composition']]
                            else:
                                signature = [nst['site'], nst['geometry']]
                            lab = sas.label_dict['|'.join(signature)]                        
                        else:
                            if sas.composition_effect:
                                signature = [nst['site'], nst['surface'], nst['composition']]
                            else:
                                signature = [nst['site'], nst['surface']]
                            lab = sas.label_dict['|'.join(signature)]
                        if lab in self.species_forbidden_labels[adsorbate]:
                            continue                                                                             
                                                                                                     
                elif self.species_forbidden_sites is not None:                          
                    if adsorbate in self.species_forbidden_sites:
                        if nst['site'] in self.species_forbidden_sites[adsorbate]:
                            continue

                if adsorbate in self.multidentate_adsorbates:                                     
                    nis = binbids[k]
                    if not self.enumerate_orientations:
                        nis = [random.choice(nis)]
                else:
                    nis = [0]
                for ni in nis:
                    # Prohibit adsorbates with more than 1 atom from entering subsurf sites
                    if len(adsorbate) > 1 and nst['site'] == '6fold':
                        continue
 
                    atoms = self.image.copy()
                    if adsorbate in self.multidentate_adsorbates:
                        # Rotate a multidentate adsorbate to all possible directions of
                        # a neighbor site
                        nbst = hsl[ni]
                        pos = nst['position'] 
                        nbpos = nbst['position'] 
                        orientation = get_mic(nbpos, pos, atoms.cell)
                        add_adsorbate_to_site(atoms, adsorbate, nst, 
                                              height=self.heights[nst['site']],
                                              orientation=orientation)        
  
                    else:
                        add_adsorbate_to_site(atoms, adsorbate, nst,
                                              height=self.heights[nst['site']])        
 
                    if True in atoms.pbc:
                        nsac = SlabAdsorbateCoverage(atoms, sas, dmax=self.dmax,
                                                     label_occupied_sites=self.unique) 
                    else: 
                        nsac = ClusterAdsorbateCoverage(atoms, sas, dmax=self.dmax,
                                                        label_occupied_sites=self.unique)
                    nhsl = nsac.hetero_site_list
  
                    # Make sure there no new site too close to previous sites after 
                    # adding the adsorbate. Useful when adding large molecules
                    if any(s for i, s in enumerate(nhsl) if s['occupied'] and (i in 
                    neighbor_site_indices)):
                        continue
                    ads_atoms = atoms[[a.index for a in atoms if                   
                                       a.symbol in adsorbate_elements]]
                    if atoms_too_close_after_addition(ads_atoms, len(list(Formula(
                    adsorbate))), self.min_adsorbate_distance, mic=(True in atoms.pbc)):
                        continue

                    labs = nsac.get_occupied_labels(fragmentation=self.enumerate_orientations)
                    if self.unique:                                        
                        G = nsac.get_graph(fragmentation=self.enumerate_orientations)
                        if labs in self.labels_list: 
                            if self.graph_list:
                                # Skip duplicates based on isomorphism 
                                potential_graphs = [g for i, g in enumerate(self.graph_list)
                                                    if self.labels_list[i] == labs]
                                # If the surface slab is clean, the potentially isomorphic
                                # graphs are all isomorphic
                                if self.clean_slab and potential_graphs:
                                    self.n_duplicate += 1
                                    continue
                                nm = iso.categorical_node_match('symbol', 'X')
                                if any(H for H in potential_graphs if 
                                nx.isomorphism.is_isomorphic(G, H, node_match=nm)):
                                    self.n_duplicate += 1
                                    continue            
                        self.labels_list.append(labs)
                        self.graph_list.append(G)                                       

                    if self.logfile is not None:                                
                        self.logfile.write('Succeed! Pattern {} '.format(self.n_write)
                                           + 'generated: {}\n'.format(labs))
                        self.logfile.flush()
                    if 'data' not in atoms.info:
                         atoms.info['data'] = {}
                    atoms.info['data']['labels'] = labs
                    self.trajectory.write(atoms)
                    self.n_write += 1

    def _remove_adsorbate(self, adsorption_sites):
        self.n_duplicate = 0                                                           
        sas = adsorption_sites
        if True in self.image.pbc:
            sac = SlabAdsorbateCoverage(self.image, sas, dmax=self.dmax,
                                        label_occupied_sites=self.unique) 
        else: 
            sac = ClusterAdsorbateCoverage(self.image, sas, dmax=self.dmax,
                                           label_occupied_sites=self.unique)
        hsl = sac.hetero_site_list
        occupied = [s for s in hsl if s['occupied']]
        if not occupied:
            if self.logfile is not None:
                self.logfile.write('There is no occupied site. Removal failed!\n')
                self.logfile.flush()
            return

        rm_ids = set()
        for rmst in occupied:
            ads_ids = set(rmst['adsorbate_indices'])
            # Make sure the same adsorbate is not removed twice
            if ads_ids.issubset(rm_ids):
                continue
            rm_ids.update(ads_ids)                
            atoms = self.image.copy()
            remove_adsorbate_from_site(atoms, rmst)

            ads_remain = [a for a in atoms if a.symbol in adsorbate_elements]
            if not ads_remain:
                if self.logfile is not None:
                    self.logfile.write('Last adsorbate has been removed ' + 
                                       'from image {}\n'.format(self.n_image))
                    self.logfile.flush()
                if 'data' not in atoms.info:
                     atoms.info['data'] = {}
                atoms.info['data']['labels'] = []
                self.trajectory.write(atoms)
                return
                                                      
            if True in atoms.pbc:                                
                nsac = SlabAdsorbateCoverage(atoms, sas, dmax=self.dmax,
                                             label_occupied_sites=self.unique) 
            else: 
                nsac = ClusterAdsorbateCoverage(atoms, sas, dmax=self.dmax,
                                                label_occupied_sites=self.unique)

            labs = nsac.get_occupied_labels(fragmentation=self.enumerate_orientations)
            if self.unique:                                        
                G = nsac.get_graph(fragmentation=self.enumerate_orientations)
                if labs in self.labels_list: 
                    if self.graph_list:
                        # Skip duplicates based on isomorphism 
                        potential_graphs = [g for i, g in enumerate(self.graph_list)
                                            if self.labels_list[i] == labs]
                        nm = iso.categorical_node_match('symbol', 'X')
                        if any(H for H in potential_graphs if 
                        nx.isomorphism.is_isomorphic(G, H, node_match=nm)):
                            self.n_duplicate += 1
                            continue            
                self.labels_list.append(labs)
                self.graph_list.append(G)                                       

            if self.logfile is not None:                                
                self.logfile.write('Succeed! Pattern {} '.format(self.n_write)
                                   + 'generated: {}\n'.format(labs))
                self.logfile.flush()
            if 'data' not in atoms.info:
                 atoms.info['data'] = {}
            atoms.info['data']['labels'] = labs
            self.trajectory.write(atoms)
            self.n_write += 1

    def _move_adsorbate(self, adsorption_sites): 
        self.n_duplicate = 0                                                           
        sas = adsorption_sites                      
        if self.adsorption_sites is not None:                            
            site_nblist = self.site_nblist
        else:
            site_nblist = sas.get_neighbor_site_list(neighbor_number=2) 

        if True in self.image.pbc:  
            sac = SlabAdsorbateCoverage(self.image, sas, dmax=self.dmax,
                                        label_occupied_sites=self.unique) 
        else: 
            sac = ClusterAdsorbateCoverage(self.image, sas, dmax=self.dmax,
                                           label_occupied_sites=self.unique)
        hsl = sac.hetero_site_list
        nbstids, selfids, occupied = [], [], []
        for j, st in enumerate(hsl):
            if st['occupied']:
                nbstids += site_nblist[j]
                selfids.append(j)
                occupied.append(st)
        if not occupied:                                                       
            if self.logfile is not None:
                self.logfile.write('There is no occupied site. Move failed!\n')
                self.logfile.flush()
            return
        nbstids = set(nbstids)
        neighbor_site_indices = [v for v in nbstids if v not in selfids]

        rm_ids = set()
        for st in occupied:
            ads_ids = set(st['adsorbate_indices'])
            # Make sure the same adsorbate is not removed twice
            if ads_ids.issubset(rm_ids):
                continue
            rm_ids.update(ads_ids)                              
            atoms = self.image.copy()
            remove_adsorbate_from_site(atoms, st)
            adsorbate = st['adsorbate']

            if adsorbate in self.multidentate_adsorbates:
                if self.adsorption_sites is not None:
                    bidentate_nblist = self.bidentate_nblist
                else:
                    bidentate_nblist = sas.get_neighbor_site_list(neighbor_number=1)
 
            # Only add one adsorabte to a site at least 2 shells away from
            # currently occupied sites
            newsites, binbids = [], []
            for i, s in enumerate(hsl):
                if i not in nbstids:
                    if adsorbate in self.multidentate_adsorbates:
                        binbs = bidentate_nblist[i]
                        binbis = [n for n in binbs if n not in nbstids]
                        if not binbis and s['site'] != '6fold':
                            continue 
                        binbids.append(binbis)
                    newsites.append(s)
 
            for k, nst in enumerate(newsites):
                if self.species_forbidden_labels is not None:
                    if adsorbate in self.species_forbidden_labels: 
                        if True in atoms.pbc:
                            if sas.composition_effect:
                                signature = [nst['site'], nst['geometry'], nst['composition']]
                            else:
                                signature = [nst['site'], nst['geometry']]
                            lab = sas.label_dict['|'.join(signature)]                        
                        else:
                            if sas.composition_effect:
                                signature = [nst['site'], nst['surface'], nst['composition']]
                            else:
                                signature = [nst['site'], nst['surface']]
                            lab = sas.label_dict['|'.join(signature)]
                        if lab in self.species_forbidden_labels[adsorbate]:
                            continue                                                          

                elif self.species_forbidden_sites is not None:                          
                    if adsorbate in self.species_forbidden_sites:
                        if nst['site'] in self.species_forbidden_sites[adsorbate]:
                            continue

                if adsorbate in self.multidentate_adsorbates:
                    nis = binbids[k]
                    if not self.enumerate_orientations:
                        nis = [random.choice(nis)]
                else:
                    nis = [0]
                for ni in nis:
                    # Prohibit adsorbates with more than 1 atom from entering subsurf 
                    if len(adsorbate) > 1 and nst['site'] == '6fold':
                        continue

                    final_atoms = atoms.copy()  
                    if adsorbate in self.multidentate_adsorbates:                     
                        # Rotate a multidentate adsorbate to all possible directions of
                        # a neighbor site
                        nbst = hsl[ni]
                        pos = nst['position'] 
                        nbpos = nbst['position'] 
                        orientation = get_mic(nbpos, pos, final_atoms.cell)
                        add_adsorbate_to_site(final_atoms, adsorbate, nst, 
                                              height=self.heights[nst['site']],
                                              orientation=orientation)        
      
                    else:
                        add_adsorbate_to_site(final_atoms, adsorbate, nst,
                                              height=self.heights[nst['site']])       

                    if True in final_atoms.pbc:   
                        nsac = SlabAdsorbateCoverage(final_atoms, sas, dmax=self.dmax,
                                                     label_occupied_sites=self.unique) 
                    else: 
                        nsac = ClusterAdsorbateCoverage(final_atoms, sas, dmax=self.dmax,
                                                        label_occupied_sites=self.unique)
                    nhsl = nsac.hetero_site_list
      
                    # Make sure there no new site too close to previous sites after 
                    # adding the adsorbate. Useful when adding large molecules
                    if any(s for i, s in enumerate(nhsl) if s['occupied'] and (i in 
                    neighbor_site_indices)):
                        continue
                    ads_atoms = final_atoms[[a.index for a in final_atoms if                   
                                             a.symbol in adsorbate_elements]]
                    if atoms_too_close_after_addition(ads_atoms, len(list(Formula(adsorbate))),
                    self.min_adsorbate_distance, mic=(True in final_atoms.pbc)):
                        continue                                                                                   

                    if True in final_atoms.pbc:
                        nsac = SlabAdsorbateCoverage(final_atoms, sas, dmax=self.dmax,
                                                     label_occupied_sites=self.unique) 
                    else: 
                        nsac = ClusterAdsorbateCoverage(final_atoms, sas, dmax=self.dmax,
                                                        label_occupied_sites=self.unique)                      
      
                    labs = nsac.get_occupied_labels(fragmentation=self.enumerate_orientations)
                    if self.unique:                                        
                        G = nsac.get_graph(fragmentation=self.enumerate_orientations)
                        if labs in self.labels_list: 
                            if self.graph_list:
                                # Skip duplicates based on isomorphism 
                                potential_graphs = [g for i, g in enumerate(self.graph_list)
                                                    if self.labels_list[i] == labs]
                                nm = iso.categorical_node_match('symbol', 'X')
                                if any(H for H in potential_graphs if 
                                nx.isomorphism.is_isomorphic(G, H, node_match=nm)):
                                    self.n_duplicate += 1
                                    continue            
                        self.labels_list.append(labs)
                        self.graph_list.append(G)                                       
                                                                                             
                    if self.logfile is not None:                                
                        self.logfile.write('Succeed! Pattern {} '.format(self.n_write)
                                           + 'generated: {}\n'.format(labs))
                        self.logfile.flush()
                    if 'data' not in final_atoms.info:
                         final_atoms.info['data'] = {}
                    final_atoms.info['data']['labels'] = labs
                    self.trajectory.write(final_atoms)
                    self.n_write += 1

    def _replace_adsorbate(self, adsorption_sites):
        sas = adsorption_sites
        if True in self.image.pbc:                                                           
            sac = SlabAdsorbateCoverage(self.image, sas, dmax=self.dmax,
                                        label_occupied_sites=self.unique)
        else: 
            sac = ClusterAdsorbateCoverage(self.image, sas, dmax=self.dmax,
                                           label_occupied_sites=self.unique)
        hsl = sac.hetero_site_list
        occupied_stids = [i for i in range(len(hsl)) if hsl[i]['occupied']]
        if not occupied_stids:
            if self.logfile is not None:
                self.logfile.write('There is no occupied site. Replacement failed!\n')
                self.logfile.flush()
            return
                                
        rm_ids = set()
        for rpsti in occupied_stids:                                                         
            rpst = hsl[rpsti]
            ads_ids = set(rpst['adsorbate_indices'])
            # Make sure the same adsorbate is not removed twice
            if ads_ids.issubset(rm_ids):
                continue
            rm_ids.update(ads_ids)                             
            atoms = self.image.copy()
            remove_adsorbate_from_site(atoms, rpst)
                                                                                             
            # Select a different adsorbate with probablity 
            old_adsorbate = rpst['adsorbate']
            new_options = [a for a in self.adsorbate_species if a != old_adsorbate]

            if self.species_forbidden_labels is not None:
                _new_options = []
                for o in new_options:
                    if o in self.species_forbidden_labels: 
                        if True in atoms.pbc:
                            if sas.composition_effect:
                                signature = [rpst['site'], rpst['geometry'], rpst['composition']]
                            else:
                                signature = [rpst['site'], rpst['geometry']]
                            lab = sas.label_dict['|'.join(signature)]                        
                                                                                                 
                        else:
                            if sas.composition_effect:
                                signature = [rpst['site'], rpst['surface'], rpst['composition']]
                            else:
                                signature = [rpst['site'], rpst['surface']]
                            lab = sas.label_dict['|'.join(signature)]                            
                        if lab not in self.species_forbidden_labels[o] :
                            _new_options.append(o)
                new_options = _new_options                                                       

            elif self.species_forbidden_sites is not None:                      
                _new_options = []
                for o in new_options: 
                    if o in self.species_forbidden_sites:
                        if rpst['site'] not in self.species_forbidden_sites[o]:
                            _new_options.append(o)
                new_options = _new_options
                                                                                             
            # Prohibit adsorbates with more than 1 atom from entering subsurf 6-fold sites
            if self.allow_6fold and rpst['site'] == '6fold':
                new_options = [o for o in new_options if len(o) == 1]
                                                                                             
            for adsorbate in new_options:
                if self.adsorption_sites is not None:
                    site_nblist = self.site_nblist
                else:
                    site_nblist = sas.get_neighbor_site_list(neighbor_number=2)
                                                                                                 
                nbstids, selfids = [], []
                for j, st in enumerate(hsl):
                    if st['occupied']:
                        nbstids += site_nblist[j]
                        selfids.append(j)
                nbstids = set(nbstids)
                neighbor_site_indices = [v for v in nbstids if v not in selfids]
                                                                                                 
                if adsorbate in self.multidentate_adsorbates:                                     
                    if self.adsorption_sites is not None:                                      
                        bidentate_nblist = self.bidentate_nblist
                    else:
                        bidentate_nblist = sas.get_neighbor_site_list(neighbor_number=1)
                    
                    binbs = bidentate_nblist[rpsti]                    
                    binbids = [n for n in binbs if n not in nbstids]
                    if not binbids:
                        continue
                    nis = binbids[k]
                    if not self.enumerate_orientations:
                        nis = [random.choice(nis)]
                else:
                    nis = [0]
                for ni in nis:                                                                                  
                    final_atoms = atoms.copy()
                    if adsorbate in self.multidentate_adsorbates:
                        # Rotate a multidentate adsorbate to all possible directions of
                        # a neighbor site
                        nbst = hsl[ni]
                        pos = rpst['position'] 
                        nbpos = nbst['position'] 
                        orientation = get_mic(nbpos, pos, final_atoms.cell)
                        add_adsorbate_to_site(final_atoms, adsorbate, rpst, 
                                              height=self.heights[rpst['site']],
                                              orientation=orientation)        
                                                                                                  
                    else:
                        add_adsorbate_to_site(final_atoms, adsorbate, rpst,
                                              height=self.heights[rpst['site']])        

                    if True in final_atoms.pbc:                                                                              
                        nsac = SlabAdsorbateCoverage(final_atoms, sas, dmax=self.dmax,
                                                     label_occupied_sites=self.unique)
                    else: 
                        nsac = ClusterAdsorbateCoverage(final_atoms, sas, dmax=self.dmax,
                                                        label_occupied_sites=self.unique)
                    nhsl = nsac.hetero_site_list
                                                                                                  
                    # Make sure there no new site too close to previous sites after 
                    # adding the adsorbate. Useful when adding large molecules
                    if any(s for i, s in enumerate(nhsl) if s['occupied'] and (i in 
                    neighbor_site_indices)):
                        continue
                    ads_atoms = final_atoms[[a.index for a in final_atoms if                   
                                             a.symbol in adsorbate_elements]]
                    if atoms_too_close_after_addition(ads_atoms, len(list(Formula(adsorbate))),  
                    self.min_adsorbate_distance, mic=(True in final_atoms.pbc)):
                        continue

                    if True in final_atoms.pbc:
                        nsac = SlabAdsorbateCoverage(final_atoms, sas, dmax=self.dmax,
                                                     label_occupied_sites=self.unique) 
                    else: 
                        nsac = ClusterAdsorbateCoverage(final_atoms, sas, dmax=self.dmax,
                                                        label_occupied_sites=self.unique)                     
      
                    labs = nsac.get_occupied_labels(fragmentation=self.enumerate_orientations)                                                   
                    if self.unique:                                        
                        G = nsac.get_graph(fragmentation=self.enumerate_orientations)
                        if labs in self.labels_list: 
                            if self.graph_list:
                                # Skip duplicates based on isomorphism 
                                potential_graphs = [g for i, g in enumerate(self.graph_list)
                                                    if self.labels_list[i] == labs]
                                nm = iso.categorical_node_match('symbol', 'X')
                                if any(H for H in potential_graphs if 
                                nx.isomorphism.is_isomorphic(G, H, node_match=nm)):
                                    self.n_duplicate += 1
                                    continue            
                        self.labels_list.append(labs)
                        self.graph_list.append(G)                                       
                                                                                             
                    if self.logfile is not None:                                
                        self.logfile.write('Succeed! Pattern {} '.format(self.n_write)
                                           + 'generated: {}\n'.format(labs))
                        self.logfile.flush()
                    if 'data' not in final_atoms.info:
                         final_atoms.info['data'] = {}
                    final_atoms.info['data']['labels'] = labs
                    self.trajectory.write(final_atoms)
                    self.n_write += 1

    def run(self, action='add'):
        self.n_write = 0
        self.n_duplicate = 0
        self.labels_list, self.graph_list = [], []

        if self.unique and self.append_trajectory:                                 
            if self.logfile is not None:                             
                self.logfile.write('Loading graphs for existing structures in ' +
                                   '{}. This might take a while.\n'.format(self.traj_name))
                self.logfile.flush()
                                                                                   
            prev_images = read(self.traj_name, index=':')
            for patoms in prev_images:
                if self.adsorption_sites is not None:
                    psas = self.adsorption_sites
                elif True in patoms.pbc:
                    if self.surface is None:
                        raise ValueError('Please specify the surface type')
                    psas = SlabAdsorptionSites(patoms, self.surface,
                                               self.allow_6fold,
                                               self.composition_effect)
                else:
                    psas = ClusterAdsorptionSites(patoms, self.allow_6fold,
                                                  self.composition_effect)      
                if True in patoms.pbc:
                    psac = SlabAdsorbateCoverage(patoms, psas, dmax=self.dmax,
                                                 label_occupied_sites=self.unique)      
                else:
                    psac = ClusterAdsorbateCoverage(patoms, psas, dmax=self.dmax,
                                                    label_occupied_sites=self.unique)        
                                                                                   
                plabs = psac.get_occupied_labels(fragmentation=self.enumerate_orientations)
                pG = psac.get_graph(fragmentation=self.enumerate_orientations)
                self.labels_list.append(plabs)
                self.graph_list.append(pG)

        for n, image in enumerate(self.images):
            if self.logfile is not None:                                   
                self.logfile.write('Generating all possible patterns '
                                   + 'for image {}\n'.format(n))
                self.logfile.flush()
            self.image = image
            self.n_image = n

            if self.adsorption_sites is not None:
                sas = self.adsorption_sites
            elif True in self.image.pbc:
                if self.surface is None:
                    raise ValueError('Please specify the surface type')
                sas = SlabAdsorptionSites(self.image, self.surface,
                                          self.allow_6fold,
                                          self.composition_effect)
            else:
                sas = ClusterAdsorptionSites(self.image, self.allow_6fold,
                                             self.composition_effect)     

            self.clean_slab = False
            self.nslab = len(sas.indices)
            if self.nslab == len(self.image):
                if action != 'add':
                    warnings.warn("There is no adsorbate in image {}. ".format(n) 
                                  + "The only available action is 'add'")        
                    continue
                self.clean_slab = True

            if action == 'add':            
                self._add_adsorbate(sas)
            elif action == 'remove':
                self._remove_adsorbate(sas)
            elif action == 'move':
                self._move_adsorbate(sas)
            elif action == 'replace':
                self._replace_adsorbate(sas)

            if self.logfile is not None:
                method = 'label match' if self.clean_slab else 'isomorphism'
                self.logfile.write('All possible patterns were generated '
                                   + 'for image {}\n'.format(n) +
                                   '{} patterns were '.format(self.n_duplicate)
                                   + 'discarded by {}\n\n'.format(method))
                self.logfile.flush()


def symmetric_coverage_pattern(atoms, adsorbate, surface=None, 
                               coverage=1., height=None, 
                               min_adsorbate_distance=0.):
    """A function for generating certain well-defined symmetric adsorbate 
       coverage patterns.

       Parameters
       ----------
       atoms: The nanoparticle or surface slab onto which the adsorbate 
              should be added.
           
       adsorbate: The adsorbate. Must be one of the following three types:
           A string containing the chemical symbol for a single atom.
           An atom object.
           An atoms object (for a molecular adsorbate).                                                                                                         
       surface: Support 2 typical surfaces for fcc crystal where the 
           adsorbate is attached:  
           'fcc100', 
           'fcc111'.
           Can either specify a string or a list of strings

       coverage: The coverage (ML) of the adsorbate.
           Note that for small nanoparticles, the function might give results 
           that do not correspond to the coverage. This is normal since the 
           surface area can be too small to encompass the coverage pattern 
           properly. We expect this function to work especially well on large 
           nanoparticles and low-index extended surfaces.                                                                                              

       height: The height from the adsorbate to the surface.
           Default is {'ontop': 2.0, 'bridge': 1.8, 'fcc': 1.8, 'hcp': 1.8, 
           '4fold': 1.7} for nanoparticles and 2.0 for all sites on surface 
           slabs.

       min_adsorbate_distance: The minimum distance between two adsorbate atoms.
       
       Example
       ------- 
       symmetric_coverage_pattern(atoms, adsorbate='CO', 
                                  surface='fcc111', 
                                  coverage=3/4)
    """

    if True not in atoms.pbc:                            
        if surface is None:
            surface = ['fcc100', 'fcc111']        
        sas = ClusterAdsorptionSites(atoms)
        site_list = sas.site_list
    else:
        sas = SlabAdsorptionSites(atoms, surface=surface)
        site_list = sas.site_list
    if not isinstance(surface, list):
        surface = [surface] 

    final_sites = []
    if 'fcc111' in surface: 
        if coverage == 1:
            fcc_sites = [s for s in site_list 
                         if s['site'] == 'fcc']
            if fcc_sites:
                final_sites += fcc_sites

        elif coverage == 3/4:
            # Kagome pattern
            fcc_sites = [s for s in site_list  
                         if s['site'] == 'fcc']
            if True not in atoms.pbc:                                
                grouped_sites = group_sites_by_surface(
                                atoms, fcc_sites, site_list)
            else:
                grouped_sites = {'pbc_sites': fcc_sites}

            for sites in grouped_sites.values():
                if sites:
                    sites_to_delete = [sites[0]]
                    for sitei in sites_to_delete:
                        common_site_indices = []
                        non_common_sites = []
                        for sitej in sites:
                            if sitej['indices'] == sitei['indices']:
                                pass
                            elif set(sitej['indices']) & set(sitei['indices']):
                                common_site_indices += list(sitej['indices'])
                            else:
                                non_common_sites.append(sitej)
                        for sitej in non_common_sites:
                            overlap = sum([common_site_indices.count(i) 
                                          for i in sitej['indices']])
                            if overlap == 1 and sitej['indices'] \
                            not in [s['indices'] for s in sites_to_delete]:
                                sites_to_delete.append(sitej)                
                    for s in sites:
                        if s['indices'] not in [st['indices'] 
                        for st in sites_to_delete]:
                            final_sites.append(s)

        elif coverage == 2/4:
            # Honeycomb pattern
            fcc_sites = [s for s in site_list if s['site'] == 'fcc']
            hcp_sites = [s for s in site_list if s['site'] == 'hcp']
            all_sites = fcc_sites + hcp_sites
            if True not in atoms.pbc:    
                grouped_sites = group_sites_by_surface(
                                atoms, all_sites, site_list)
            else:
                grouped_sites = {'pbc_sites': all_sites}
            for sites in grouped_sites.values():
                if sites:                    
                    sites_to_remain = [sites[0]]
                    for sitei in sites_to_remain:
                        for sitej in sites:
                            if sitej['indices'] == sitei['indices']:
                                pass
                            elif len(set(sitej['indices']) & \
                            set(sitei['indices'])) == 1 \
                            and sitej['site'] != sitei['site'] \
                            and sitej['indices'] not in [s['indices'] 
                            for s in sites_to_remain]:
                                sites_to_remain.append(sitej)
                    final_sites += sites_to_remain                                         

            if True not in atoms.pbc:                                                                       
                bad_sites = []
                for sti in final_sites:
                    if sti['site'] == 'hcp':
                        count = 0
                        for stj in final_sites:
                            if stj['site'] == 'fcc':
                                if len(set(stj['indices']) & \
                                set(sti['indices'])) == 2:
                                    count += 1
                        if count != 0:
                            bad_sites.append(sti)
                final_sites = [s for s in final_sites if s['indices'] \
                               not in [st['indices'] for st in bad_sites]]

        elif coverage == 1/4:
            # Kagome pattern
            fcc_sites = [s for s in site_list 
                         if s['site'] == 'fcc']                                                                 
            if True not in atoms.pbc:                                
                grouped_sites = group_sites_by_surface(
                                atoms, fcc_sites, site_list)
            else:
                grouped_sites = {'pbc_sites': fcc_sites}

            for sites in grouped_sites.values():
                if sites:
                    sites_to_remain = [sites[0]]
                    for sitei in sites_to_remain:
                        common_site_indices = []
                        non_common_sites = []
                        for sitej in sites:
                            if sitej['indices'] == sitei['indices']:
                                pass
                            elif set(sitej['indices']) & set(sitei['indices']):
                                common_site_indices += list(sitej['indices'])
                            else:
                                non_common_sites.append(sitej)
                        for sitej in non_common_sites:
                            overlap = sum([common_site_indices.count(i) 
                                          for i in sitej['indices']])
                            if overlap == 1 and sitej['indices'] \
                            not in [s['indices'] for s in sites_to_remain]:
                                sites_to_remain.append(sitej)               
                    final_sites += sites_to_remain

    if 'fcc100' in surface:
        if coverage == 1:
            fold4_sites = [s for s in site_list if s['site'] == '4fold']
            if fold4_sites:
                final_sites += fold4_sites

        elif coverage == 3/4:
            fold4_sites = [s for s in site_list if s['site'] == '4fold']
            if True not in atoms.pbc:                                           
                grouped_sites = group_sites_by_surface(
                                atoms, fold4_sites, site_list)
            else:
                grouped_sites = {'pbc_sites': fold4_sites}
            for sites in grouped_sites.values():
                if sites:
                    sites_to_delete = [sites[0]]
                    for sitei in sites_to_delete:
                        common_site_indices = []
                        non_common_sites = []
                        for sitej in sites:
                            if sitej['indices'] == sitei['indices']:
                                pass
                            elif set(sitej['indices']) & set(sitei['indices']):
                                common_site_indices += list(sitej['indices'])
                            else:
                                non_common_sites.append(sitej)                        
                        for sitej in non_common_sites:                        
                            overlap = sum([common_site_indices.count(i) 
                                          for i in sitej['indices']])                        
                            if overlap in [1, 4] and sitej['indices'] not in \
                            [s['indices'] for s in sites_to_delete]:  
                                sites_to_delete.append(sitej)
                    for s in sites:
                        if s['indices'] not in [st['indices'] 
                                   for st in sites_to_delete]:
                            final_sites.append(s)

        elif coverage == 2/4:
            #c(2x2) pattern
            fold4_sites = [s for s in site_list if s['site'] == '4fold']
            original_sites = deepcopy(fold4_sites)
            if True not in atoms.pbc:
                grouped_sites = group_sites_by_surface(
                                atoms, fold4_sites, site_list)
            else:
                grouped_sites = {'pbc_sites': fold4_sites}
            for sites in grouped_sites.values():
                if sites:
                    sites_to_remain = [sites[0]]
                    for sitei in sites_to_remain:
                        for sitej in sites:
                            if (len(set(sitej['indices']) & \
                            set(sitei['indices'])) == 1) and \
                            (sitej['indices'] not in [s['indices'] 
                            for s in sites_to_remain]):
                                sites_to_remain.append(sitej)
                    for s in original_sites:
                        if s['indices'] in [st['indices'] 
                        for st in sites_to_remain]:
                            final_sites.append(s)

        elif coverage == 1/4:
            #p(2x2) pattern
            fold4_sites = [s for s in site_list if s['site'] == '4fold']
            if True not in atoms.pbc:                                           
                grouped_sites = group_sites_by_surface(
                                atoms, fold4_sites, site_list)
            else:
                grouped_sites = {'pbc_sites': fold4_sites}
            for sites in grouped_sites.values():
                if sites:
                    sites_to_remain = [sites[0]]
                    for sitei in sites_to_remain:
                        common_site_indices = []
                        non_common_sites = []
                        for idx, sitej in enumerate(sites):
                            if sitej['indices'] == sitei['indices']:
                                pass
                            elif set(sitej['indices']) & set(sitei['indices']):
                                common_site_indices += list(sitej['indices'])
                            else:
                                non_common_sites.append(sitej)
                        for sitej in non_common_sites:
                            overlap = sum([common_site_indices.count(i) 
                                          for i in sitej['indices']])
                            if overlap in [1, 4] and sitej['indices'] not in \
                            [s['indices'] for s in sites_to_remain]:  
                                sites_to_remain.append(sitej)
                    final_sites += sites_to_remain

    # Add edge coverage for nanoparticles
    if True not in atoms.pbc:
        if coverage == 1:
            edge_sites = [s for s in site_list if 
                          s['site'] == 'bridge' and 
                          s['surface'] == 'edge']
            vertex_indices = [s['indices'][0] for 
                              s in site_list if 
                              s['site'] == 'ontop' and 
                              s['surface'] == 'vertex']
            ve_common_indices = set()
            for esite in edge_sites:
                if set(esite['indices']) & set(vertex_indices):
                    for i in esite['indices']:
                        if i not in vertex_indices:
                            ve_common_indices.add(i)
            for esite in edge_sites:
                if not set(esite['indices']).issubset(
                ve_common_indices):
                    final_sites.append(esite)

        if coverage == 3/4:
            occupied_sites = final_sites.copy()
            hcp_sites = [s for s in site_list if 
                         s['site'] == 'hcp' and
                         s['surface'] == 'fcc111']
            edge_sites = [s for s in site_list if 
                          s['site'] == 'bridge' and
                          s['surface'] == 'edge']
            vertex_indices = [s['indices'][0] for 
                              s in site_list if
                              s['site'] == 'ontop' and 
                              s['surface'] == 'vertex']
            ve_common_indices = set()
            for esite in edge_sites:
                if set(esite['indices']) & set(vertex_indices):
                    for i in esite['indices']:
                        if i not in vertex_indices:
                            ve_common_indices.add(i)                
            for esite in edge_sites:
                if not set(esite['indices']).issubset(
                ve_common_indices):
                    intermediate_indices = []
                    for hsite in hcp_sites:
                        if len(set(esite['indices']) & \
                               set(hsite['indices'])) == 2:
                            intermediate_indices.append(min(
                            set(esite['indices']) ^ \
                            set(hsite['indices'])))
                    too_close = 0
                    for s in occupied_sites:
                        if len(set(esite['indices']) & \
                        set(s['indices'])) == 2:
                            too_close += 1
                    share = [0]
                    for interi in intermediate_indices:
                        share.append(len([s for s in occupied_sites if \
                                          interi in s['indices']]))
                    if max(share) <= 2 and too_close == 0:
                        final_sites.append(esite)

        if coverage == 2/4:            
            occupied_sites = final_sites.copy()
            edge_sites = [s for s in site_list if 
                          s['site'] == 'bridge' and
                          s['surface'] == 'edge']
            vertex_indices = [s['indices'][0] for 
                              s in site_list if
                              s['site'] == 'ontop' and 
                              s['surface'] == 'vertex']
            ve_common_indices = set()
            for esite in edge_sites:
                if set(esite['indices']) & set(vertex_indices):
                    for i in esite['indices']:
                        if i not in vertex_indices:
                            ve_common_indices.add(i)                
            for esite in edge_sites:
                if not set(esite['indices']).issubset(
                ve_common_indices):
                    intermediate_indices = []
                    for hsite in hcp_sites:
                        if len(set(esite['indices']) & \
                               set(hsite['indices'])) == 2:
                            intermediate_indices.append(min(
                            set(esite['indices']) ^ \
                            set(hsite['indices'])))
                    share = [0]
                    for interi in intermediate_indices:
                        share.append(len([s for s in occupied_sites if \
                                          interi in s['indices']]))
                    too_close = 0
                    for s in occupied_sites:
                        if len(set(esite['indices']) & \
                        set(s['indices'])) == 2:
                            too_close += 1
                    if max(share) <= 1 and too_close == 0:
                        final_sites.append(esite)

        if coverage == 1/4:
            occupied_sites = final_sites.copy()
            hcp_sites = [s for s in site_list if 
                         s['site'] == 'hcp' and
                         s['surface'] == 'fcc111']
            edge_sites = [s for s in site_list if 
                          s['site'] == 'bridge' and
                          s['surface'] == 'edge']
            vertex_indices = [s['indices'][0] for 
                              s in site_list if
                              s['site'] == 'ontop' and 
                              s['surface'] == 'vertex'] 
            ve_common_indices = set()
            for esite in edge_sites:
                if set(esite['indices']) & set(vertex_indices):
                    for i in esite['indices']:
                        if i not in vertex_indices:
                            ve_common_indices.add(i)                
            for esite in edge_sites:
                if not set(esite['indices']).issubset(
                ve_common_indices):
                    intermediate_indices = []
                    for hsite in hcp_sites:
                        if len(set(esite['indices']) & \
                        set(hsite['indices'])) == 2:
                            intermediate_indices.append(min(
                             set(esite['indices']) ^ \
                             set(hsite['indices'])))
                    share = [0]
                    for interi in intermediate_indices:
                        share.append(len([s for s in occupied_sites if \
                                          interi in s['indices']]))
                    too_close = 0
                    for s in occupied_sites:
                        if len(set(esite['indices']) & \
                        set(s['indices'])) > 0:
                            too_close += 1
                    if max(share) == 0 and too_close == 0:
                        final_sites.append(esite)

    natoms = len(atoms)
    nads = len(list(Formula(adsorbate)))
    for site in final_sites:
        if height is None:
            height = site_heights[site['site']]

        add_adsorbate_to_site(atoms, adsorbate, site, height)       
        if min_adsorbate_distance > 0:
            if atoms_too_close_after_addition(atoms[natoms:], nads,
            min_adsorbate_distance, mic=(True in atoms.pbc)): 
                atoms = atoms[:-nads]

    return atoms


def full_coverage_pattern(atoms, adsorbate, site, surface=None,
                          height=None, min_adsorbate_distance=0.):
    """A function to generate different 1ML coverage patterns"""

    if True not in atoms.pbc:                                 
        if surface is None:
            surface = ['fcc100', 'fcc111']        
        sas = ClusterAdsorptionSites(atoms, allow_6fold=True)
        site_list = sas.site_list
    else:
        sas = SlabAdsorptionSites(atoms, surface=surface,
                                  allow_6fold=True)
        site_list = sas.site_list
    if not isinstance(surface, list):
        surface = [surface] 

    natoms = len(atoms)
    nads = len(list(Formula(adsorbate)))
    for st in site_list:
        if st['site'] == site and st['surface'] in surface:
            if height is None:
                height = site_heights[st['site']]
            add_adsorbate_to_site(atoms, adsorbate, st, height)       
            if min_adsorbate_distance > 0:
                if atoms_too_close_after_addition(atoms[natoms:], nads,
                min_adsorbate_distance, mic=(True in atoms.pbc)):
                    atoms = atoms[:-nads]                               

    return atoms


def random_coverage_pattern(atoms, adsorbate_species, 
                            surface=None, 
                            min_adsorbate_distance=1.5, 
                            heights=site_heights,
                            allow_6fold=False):
    '''
    A function for generating random coverage patterns with minimum distance constraint

    Parameters
    ----------
    atoms: The nanoparticle or surface slab onto which the adsorbate should be added.
        
    adsorbate: The adsorbate. Must be one of the following three types:
        A string containing the chemical symbol for a single atom.
        An atom object.
        An atoms object (for a molecular adsorbate).                                                                                                       
    min_adsorbate_distance: The minimum distance constraint between any two adsorbates.

    heights: A dictionary that contains the adsorbate height for each site type.
    '''
    adsorbate_species = adsorbate_species if is_list_or_tuple(
                        adsorbate_species) else [adsorbate_species]
    if species_probabilities is not None:
        assert len(self.species_probabilities.keys()) == len(self.adsorbate_species)
        probability_list = [species_probabilities[a] for a in adsorbate_species]               
 
    if True not in atoms.pbc:                                
        sas = ClusterAdsorptionSites(atoms, allow_6fold=allow_6fold)
        site_list = sas.site_list
    else:
        sas = SlabAdsorptionSites(atoms, surface=surface,
                                  allow_6fold=allow_6fold)
        site_list = sas.site_list

    random.shuffle(site_list)
    natoms = len(atoms)
    nads_dict = {ads: len(list(Formula(ads))) for ads in adsorbate_species}

    for st in site_list:
        # Select adsorbate with probablity 
        if not species_probabilities:
            adsorbate = random.choice(adsorbate_species)
        else: 
            adsorbate = random.choices(k=1, population=adsorbate_species,
                                       probabilities=probability_list)[0] 
        nads = nads_dict[adsorbate] 
        height = heights[st['site']]
        add_adsorbate_to_site(atoms, adsorbate, st, height)       
        if min_adsorbate_distance > 0:
            if atoms_too_close_after_addition(atoms[natoms:], nads,
            min_adsorbate_distance, mic=(True in atoms.pbc)):
                atoms = atoms[:-nads]                               

    return atoms
