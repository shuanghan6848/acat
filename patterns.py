from .adsorption_sites import * 
from .adsorbate_coverage import *
from .utilities import *
from .settings import *
from .actions import *
from ase.io import read, write, Trajectory
from ase.formula import Formula
from asap3 import FullNeighborList
import networkx.algorithms.isomorphism as iso
import networkx as nx
import numpy as np
import warnings
import random
import copy


class StochasticPatternGenerator(object):

    def __init__(self, images,                                                       
                 monodentate_adsorbates=None,
                 multidentate_adsorbates=None,
                 adsorbate_weights=None,
                 min_adsorbate_distance=1.5,
                 adsorption_sites=None,
                 surface=None,
                 heights=site_heights,
                 allow_6fold=False,
                 composition_effect=True,
                 unique=True,
                 trajectory='patterns.traj',
                 logfile='patterns.log'):
        """
        adsorbate_weights: dictionary   
        adsorption_sites: should only provide when the surface composition is fixed
        """

        if not is_list_or_tuple(images):
            images = [images]
        monodentate_adsorbates = [] if not monodentate_adsorbates \
                                 else monodentate_adsorbates 
        multidentate_adsorbates = [] if not multidentate_adsorbates \
                                  else multidentate_adsorbates       
        if not is_list_or_tuple(monodentate_adsorbates):   
            monodentate_adsorbates = [monodentate_adsorbates]
        if not is_list_or_tuple(monodentate_adsorbates):
            multidentate_adsorbates = [multidentate_adsorbates] 
 
        self.images = images
        self.monodentate_adsorbates = monodentate_adsorbates
        self.multidentate_adsorbates = multidentate_adsorbates
        self.adsorbates = monodentate_adsorbates + multidentate_adsorbates
        self.adsorbate_weights = adsorbate_weights
        if self.adsorbate_weights is not None:
            assert len(self.adsorbate_weights.keys()) == len(self.adsorbates)
            self.all_weights = [self.adsorbate_weights[a] for a in self.adsorbates]
         
        self.min_adsorbate_distance = min_adsorbate_distance
        self.adsorption_sites = adsorption_sites
        self.surface = surface
        self.heights = heights
        self.allow_6fold = allow_6fold
        self.composition_effect = composition_effect
        self.unique = unique
        if isinstance(trajectory, str):            
            self.trajectory = Trajectory(trajectory, mode='w')
        if isinstance(logfile, str):
            self.logfile = open(logfile, 'a')      
 
        if self.adsorption_sites is not None:
            if self.multidentate_adsorbates is not None:
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
            sac = SlabAdsorbateCoverage(self.atoms, sas) if True in self.atoms.pbc \
                  else ClusterAdsorbateCoverage(self.atoms, sas)
            hsl = sac.hetero_site_list
            nbstids, selfids = [], []
            for j, st in enumerate(hsl):
                if st['occupied'] == 1:
                    nbstids += site_nblist[j]
                    selfids.append(j)
            nbstids = set(nbstids)
            neighbor_site_indices = [v for v in nbstids if v not in selfids]            
                                                                                             
        # Select adsorbate with probablity 
        if not self.adsorbate_weights:
            adsorbate = random.choice(self.adsorbates)
        else: 
            adsorbate = random.choices(k=1, population=self.adsorbates,
                                       weights=self.all_weights)[0] 
                                                                                             
        # Only add one adsorabte to a site at least 2 shells 
        # away from currently occupied sites
        nsids = [i for i, s in enumerate(hsl) if i not in nbstids]
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

        nsac = SlabAdsorbateCoverage(self.atoms, sas) if True in self.atoms.pbc \
               else ClusterAdsorbateCoverage(self.atoms, sas)
        nhsl = nsac.hetero_site_list
                                                                           
        # Make sure there no new site too close to previous sites after 
        # the action. Useful when adding large molecules
        if any(s for i, s in enumerate(nhsl) if (s['occupied'] == 1)
        and (i in neighbor_site_indices)):
            if self.logfile is not None:
                self.logfile.write('The added {} is too close '.format(adsorbate)
                                   + 'to another adsorbate. Addition failed!\n')
                self.logfile.flush()
            return
        ads_atoms = self.atoms[[a.index for a in self.atoms if                   
                                a.symbol in adsorbate_elements]]
        if added_atoms_too_close(ads_atoms, n_added=len(list(Formula(adsorbate))), 
        cutoff=self.min_adsorbate_distance, mic=(True in self.atoms.pbc)):
            if self.logfile is not None:
                self.logfile.write('The added {} is too close '.format(adsorbate)
                                   + 'to another adsorbate. Addition failed!\n')
                self.logfile.flush()
            return

        return nsac                                                                

    def _remove_adsorbate(self, adsorption_sites):
        sas = adsorption_sites                      
        sac = SlabAdsorbateCoverage(self.atoms, sas) if True in self.atoms.pbc \
              else ClusterAdsorbateCoverage(self.atoms, sas)
        hsl = sac.hetero_site_list
        occupied = [s for s in hsl if s['occupied'] == 1]
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
                self.logfile.write('There is only one adsorbate left. ' 
                                   + 'Removal failed!\n')
                self.logfile.flush()
            return

        nsac = SlabAdsorbateCoverage(self.atoms, sas) if True in self.atoms.pbc \
               else ClusterAdsorbateCoverage(self.atoms, sas)
        return nsac 

    def _move_adsorbate(self, adsorption_sites):           
        sas = adsorption_sites
        if self.adsorption_sites is not None:
            site_nblist = self.site_nblist
        else:
            site_nblist = sas.get_neighbor_site_list(neighbor_number=2) 
                                                                        
        sac = SlabAdsorbateCoverage(self.atoms, sas) if True in self.atoms.pbc \
              else ClusterAdsorbateCoverage(self.atoms, sas)
        hsl = sac.hetero_site_list
        occupied = [s for s in hsl if s['occupied'] == 1]                         
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
            if st['occupied'] == 1:
                nbstids += site_nblist[j]
                selfids.append(j)
        nbstids = set(nbstids)
        neighbor_site_indices = [v for v in nbstids if v not in selfids]
                                                                                        
        # Only add one adsorabte to a site at least 2 shells 
        # away from currently occupied sites
        nsids = [i for i, s in enumerate(hsl) if i not in nbstids]
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

        nsac = SlabAdsorbateCoverage(self.atoms, sas) if True in self.atoms.pbc \
               else ClusterAdsorbateCoverage(self.atoms, sas)
        nhsl = nsac.hetero_site_list
                                                                           
        # Make sure there no new site too close to previous sites after 
        # the action. Useful when adding large molecules
        if any(s for i, s in enumerate(nhsl) if (s['occupied'] == 1)
        and (i in neighbor_site_indices)):
            if self.logfile is not None:
                self.logfile.write('The new position of {} is too '.format(adsorbate)
                                   + 'close to another adsorbate. Move failed!\n')
                self.logfile.flush()
            return
        ads_atoms = self.atoms[[a.index for a in self.atoms if                   
                                a.symbol in adsorbate_elements]]
        if added_atoms_too_close(ads_atoms, n_added=len(list(Formula(adsorbate))), 
        cutoff=self.min_adsorbate_distance, mic=(True in self.atoms.pbc)):
            if self.logfile is not None:
                self.logfile.write('The new position of {} is too '.format(adsorbate)
                                   + 'close to another adsorbate. Move failed!\n')
                self.logfile.flush()
            return
 
        return nsac                                                                 

    def _replace_adsorbate(self, adsorption_sites):
        sas = adsorption_sites
        sac = SlabAdsorbateCoverage(self.atoms, sas) if True in self.atoms.pbc \
              else ClusterAdsorbateCoverage(self.atoms, sas)
        hsl = sac.hetero_site_list
        occupied = [i for i in range(len(hsl)) if hsl[i]['occupied'] == 1]
        if not occupied:
            if self.logfile is not None:
                self.logfile.write('There is no occupied site. Replacement failed!\n')
                self.logfile.flush()
            return

        rpsti = random.choice(occupied)
        rpst = hsl[rpsti]
        remove_adsorbate_from_site(self.atoms, rpst)

        # Select a different adsorbate with probablity 
        old_adsorbate = rpst['adsorbate']
        new_options = [a for a in self.adsorbates if a != old_adsorbate]

        # Prohibit adsorbates with more than 1 atom from entering subsurf 6-fold sites
        if self.allow_6fold and rpst['site'] == '6fold':
            new_options = [o for o in new_options if len(o) == 1]

        if not self.adsorbate_weights:
            adsorbate = random.choice(new_options)
        else:
            new_weights = [self.adsorbate_weights[a] for a in new_options]
            adsorbate = random.choices(k=1, population=self.adsorbates,
                                       weights=new_weights)[0] 
        if self.adsorption_sites is not None:
            site_nblist = self.site_nblist
        else:
            site_nblist = sas.get_neighbor_site_list(neighbor_number=2)

        nbstids, selfids = [], []
        for j, st in enumerate(hsl):
            if st['occupied'] == 1:
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
   
        nsac = SlabAdsorbateCoverage(self.atoms, sas) if True in self.atoms.pbc \
               else ClusterAdsorbateCoverage(self.atoms, sas)         
        nhsl = nsac.hetero_site_list                            
                                                                           
        # Make sure there no new site too close to previous sites after 
        # the action. Useful when adding large molecules
        if any(s for i, s in enumerate(nhsl) if (s['occupied'] == 1)
        and (i in neighbor_site_indices)):
            if self.logfile is not None:
                self.logfile.write('The added {} is too close '.format(adsorbate)
                                   + 'to another adsorbate. Replacement failed!\n')
                self.logfile.flush()
            return
        ads_atoms = self.atoms[[a.index for a in self.atoms if                   
                                a.symbol in adsorbate_elements]]
        if added_atoms_too_close(ads_atoms, n_added=len(list(Formula(adsorbate))), 
        cutoff=self.min_adsorbate_distance, mic=(True in self.atoms.pbc)):
            if self.logfile is not None:
                self.logfile.write('The added {} is too close '.format(adsorbate)
                                   + 'to another adsorbate. Replacement failed!\n')
                self.logfile.flush()
            return

        return nsac                        
 
    def run(self, n_gen, 
            actions=['add','remove','replace'], 
            action_weights=None):
        
        if not is_list_or_tuple(actions):
            actions = [actions]
        if action_weights is not None:
            all_action_weights = [action_weights[a] for a in actions]
        
        self.labels_list, self.graph_list = [], []
        n_new = 0
        n_old = 0
        # Start the iteration
        while n_new < n_gen:
            if n_old == n_new:
                if self.logfile is not None:                                    
                    self.logfile.write('Generating pattern {}\n'.format(n_new))
                    self.logfile.flush()
                n_old += 1

            self.atoms = random.choice(self.images).copy()
            if self.adsorption_sites is not None:
                sas = self.adsorption_sites
            elif True in self.atoms.pbc:
                sas = SlabAdsorptionSites(self.atoms, self.surface,
                                          self.allow_6fold,
                                          self.composition_effect)
            else:
                sas = ClusterAdsorptionSites(self.atoms, self.allow_6fold,
                                             self.composition_effect)      
            # Choose an action 
            self.clean_slab = False
            ads = [a for a in self.atoms if a.symbol in adsorbate_elements]
            if not ads:
                if 'add' not in actions:                                                             
                    warnings.warn("There is no adsorbate in image {}. ".format(n)
                                  + "The only available action is 'add'")
                    continue 
                else:
                    action = 'add'
                    self.clean_slab = True
            else:
                if not action_weights:
                    action = random.choice(actions)
                else:
                    assert len(action_weights.keys()) == len(actions)
                    action = random.choices(k=1, population=actions, 
                                            weights=all_action_weights)[0] 
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
            
            labs = nsac.labels
          #  print('labs:', labs)
            if self.unique:
                G = nsac.get_graph()
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
            self.trajectory.write(self.atoms)
            n_new += 1


class SystematicPatternGenerator(object):

    def __init__(self, images,                                                     
                 monodentate_adsorbates=None,
                 multidentate_adsorbates=None,
                 min_adsorbate_distance=1.5,
                 adsorption_sites=None,
                 surface=None,
                 heights=site_heights,
                 allow_6fold=False,
                 composition_effect=True,
                 unique=True,
                 trajectory='patterns.traj',
                 logfile='patterns.log'):
        """adsorbate_weights: dictionary"""
        if not is_list_or_tuple(images):
            images = [images]
        monodentate_adsorbates = [] if not monodentate_adsorbates \
                                 else monodentate_adsorbates 
        multidentate_adsorbates = [] if not multidentate_adsorbates \
                                  else multidentate_adsorbates       
        if not is_list_or_tuple(monodentate_adsorbates):   
            monodentate_adsorbates = [monodentate_adsorbates]
        if not is_list_or_tuple(monodentate_adsorbates):
            multidentate_adsorbates = [multidentate_adsorbates] 
 
        self.images = images
        self.monodentate_adsorbates = monodentate_adsorbates
        self.multidentate_adsorbates = multidentate_adsorbates
        self.adsorbates = monodentate_adsorbates + multidentate_adsorbates
 
        self.min_adsorbate_distance = min_adsorbate_distance
        self.adsorption_sites = adsorption_sites
        self.surface = surface
        self.heights = heights        
        self.unique = unique
        if isinstance(trajectory, str):            
            self.trajectory = Trajectory(trajectory, mode='w')
        if isinstance(logfile, str):
            self.logfile = open(logfile, 'a')                 
 
        if self.adsorption_sites is not None:
            if self.multidentate_adsorbates is not None:
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
            sac = SlabAdsorbateCoverage(self.image, sas) if True in self.image.pbc \
                  else ClusterAdsorbateCoverage(self.image, sas)
            hsl = sac.hetero_site_list
            nbstids, selfids = [], []
            for j, st in enumerate(hsl):
                if st['occupied'] == 1:
                    nbstids += site_nblist[j]
                    selfids.append(j)
            nbstids = set(nbstids)
            neighbor_site_indices = [v for v in nbstids if v not in selfids]

        if self.multidentate_adsorbates is not None:
            if self.adsorption_sites is not None:
                bidentate_nblist = self.bidentate_nblist
            else:
                bidentate_nblist = sas.get_neighbor_site_list(neighbor_number=1)

        # Only add one adsorabte to a site at least 2 shells away from
        # currently occupied sites
        newsites, binbids = [], []
        for i, s in enumerate(hsl):
            if i not in nbstids:
                if self.multidentate_adsorbates is not None:
                    binbs = bidentate_nblist[i]
                    binbis = [n for n in binbs if n not in nbstids]
                    if not binbis and s['site'] != '6fold':
                        continue 
                    binbids.append(binbis)
                newsites.append(s)

        for k, nst in enumerate(newsites): 
            for adsorbate in self.adsorbates:
                if adsorbate in self.multidentate_adsorbates:
                    nis = binbids[k]
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
  
                    nsac = SlabAdsorbateCoverage(atoms, sas) if True in atoms.pbc \
                           else ClusterAdsorbateCoverage(atoms, sas)
                    nhsl = nsac.hetero_site_list
  
                    # Make sure there no new site too close to previous sites after 
                    # adding the adsorbate. Useful when adding large molecules
                    if any(s for i, s in enumerate(nhsl) if (s['occupied'] == 1)
                    and (i in neighbor_site_indices)):
                        continue
                    ads_atoms = self.atoms[[a.index for a in self.atoms if                   
                                            a.symbol in adsorbate_elements]]
                    if added_atoms_too_close(ads_atoms, n_added=len(list(Formula(adsorbate))),  
                    cutoff=self.min_adsorbate_distance, mic=(True in self.atoms.pbc)):
                        continue

                    labs = nsac.labels
                    if self.unique:                                        
                        G = nsac.get_graph()
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
                    self.trajectory.write(atoms)
                    self.n_write += 1

    def run(self, action='add'):
        self.n_write = 0
        self.n_duplicate = 0
        self.labels_list = []
        self.graph_list = []      
        for n, image in enumerate(self.images):
            if self.logfile is not None:                                   
                self.logfile.write('Generating all possible patterns '
                                   + 'for image {}\n'.format(n))
                self.logfile.flush()
            self.image = image

            if self.adsorption_sites is not None:
                sas = self.adsorption_sites
            elif True in self.image.pbc:
                sas = SlabAdsorptionSites(self.image, self.surface,
                                          self.allow_6fold,
                                          self.composition_effect)
            else:
                sas = ClusterAdsorptionSites(self.image, self.allow_6fold,
                                             self.composition_effect)     

            self.clean_slab = False
            ads = [a for a in self.image if a.symbol in adsorbate_elements] 
            if not ads:
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

       min_adsorbate_distance: The minimum distance between two adsorbate 
           atoms. Default value 0.2 is good for adsorbate coverage patterns. 
           Play around to find the best value.
       
       Example
       ------- 
       pattern_generator(atoms, adsorbate='CO', surface='fcc111', coverage=3/4)
    """

    ads_indices = [a.index for a in atoms if 
                   a.symbol in adsorbate_elements]
    ads_atoms = None
    if ads_indices:
        ads_atoms = atoms[ads_indices]
        atoms = atoms[[a.index for a in atoms if 
                       a.symbol not in adsorbate_elements]]
    ads = adsorbate_molecule(adsorbate)

    if True not in atoms.pbc:                            
        if surface is None:
            surface = ['fcc100', 'fcc111']        
        sas = ClusterAdsorptionSites(atoms)
        site_list = sas.site_list
    else:
        sas = SlabAdsorptionSites(atoms, surface=surface)
        if surface is None:
            surface = sas.surface
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
            original_sites = copy.deepcopy(fold4_sites)
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

    for site in final_sites:
        add_adsorbate_to_site(atoms, adsorbate, site, height)

    if min_adsorbate_distance > 0.:
        if True not in atoms.pbc:
            sac = ClusterAdsorbateCoverage(atoms, sas)
        else:
            sac = SlabAdsorbateCoverage(atoms, sas)        
        remove_adsorbates_too_close(atoms, sac, min_adsorbate_distance)

    return atoms


def full_coverage_pattern(atoms, adsorbate, site, height=None, 
                          min_adsorbate_distance=0.6):
    '''A function to generate different 1ML coverage patterns'''

    ads_indices = [a.index for a in atoms if a.symbol in adsorbate_elements]
    ads_atoms = None
    if ads_indices:
        ads_atoms = atoms[ads_indices]
        atoms = atoms[[a.index for a in atoms if a.symbol not in adsorbate_elements]]
    ads = molecule(adsorbate)[::-1]
    if str(ads.symbols) != 'CO':
        ads.set_chemical_symbols(ads.get_chemical_symbols()[::-1])
    final_sites = []
    positions = []
    if site == 'fcc':
        return symmetric_pattern_generator(atoms, adsorbate, coverage=1, height=height, 
                                           min_adsorbate_distance=min_adsorbate_distance)
    elif site == 'ontop':
        sites = get_monometallic_sites(atoms, site='ontop', surface='fcc100') +\
                get_monometallic_sites(atoms, site='ontop', surface='fcc111') +\
                get_monometallic_sites(atoms, site='ontop', surface='edge') +\
                get_monometallic_sites(atoms, site='ontop', surface='vertex')
        if sites:
            final_sites += sites
            positions += [s['adsorbate_position'] for s in sites]
    elif site in ['hcp', '4fold']:
        if True not in atoms.pbc:
            sites = get_monometallic_sites(atoms, site='hcp', surface='fcc111', height=height) +\
                    get_monometallic_sites(atoms, site='4fold', surface='fcc100', height=height)
        else:
            sites = get_monometallic_sites(atoms, site='hcp', surface='fcc111', height=height)
        if sites:
            final_sites += sites
            positions += [s['adsorbate_position'] for s in sites]

    if True not in atoms.pbc:
        if adsorbate == 'CO':
            for site in final_sites:
                add_adsorbate(atoms, molecule(adsorbate)[::-1], site)
            nl = FullNeighborList(rCut=min_adsorbate_distance, atoms=atoms)     
            nl.update(atoms)            
            atom_indices = [a.index for a in atoms if a.symbol == 'O']            
            n_ads_atoms = 2
            overlap_atoms_indices = []
            for idx in atom_indices:   
                neighbor_indices, _ = nl.get_neighbors(idx)
                overlap = 0
                for i in neighbor_indices:
                    if (atoms[i].symbol in adsorbate_elements) and (i not in overlap_atoms_indices):
                        overlap += 1
                if overlap > 0:
                    overlap_atoms_indices += list(set([idx-n_ads_atoms+1, idx]))
            del atoms[overlap_atoms_indices]

        else:
            for site in final_sites:
                add_adsorbate(atoms, molecule(adsorbate), site)
            nl = FullNeighborList(rCut=min_adsorbate_distance, atoms=atoms)   
            nl.update(atoms)            
            atom_indices = [a.index for a in atoms if a.symbol == adsorbate[-1]]
            ads_symbols = molecule(adsorbate).get_chemical_symbols()
            n_ads_atoms = len(ads_symbols)
            overlap_atoms_indices = []
            for idx in atom_indices:   
                neighbor_indices, _ = nl.get_neighbors(idx)
                overlap = 0
                for i in neighbor_indices:                                                                
                    if (atoms[i].symbol in adsorbate_elements) and (i not in overlap_atoms_indices):                       
                        overlap += 1                                                                      
                if overlap > 0:                                                                           
                    overlap_atoms_indices += list(set([idx-n_ads_atoms+1, idx]))                                
            del atoms[overlap_atoms_indices]                                                                    

    else:
        for pos in positions:
            ads.translate(pos - ads[0].position)
            atoms += ads
        if ads_indices:
            atoms += ads_atoms

    return atoms


def random_coverage_pattern(atoms, adsorbate, surface=None, 
                            min_adsorbate_distance=2., 
                            heights=site_heights):
    '''A function for generating random coverage patterns with constraint.
       Parameters
       ----------
       atoms: The nanoparticle or surface slab onto which the adsorbate should be added.
           
       adsorbate: The adsorbate. Must be one of the following three types:
           A string containing the chemical symbol for a single atom.
           An atom object.
           An atoms object (for a molecular adsorbate).                                                                                                       
       min_adsorbate_distance: The minimum distance constraint between any two adsorbates.

       heights: A dictionary that contains the adsorbate height for each site type.'''
 
    ads_indices = [a.index for a in atoms if a.symbol in adsorbate_elements]
    ads_atoms = None
    if ads_indices:
        ads_atoms = atoms[ads_indices]
        atoms = atoms[[a.index for a in atoms if a.symbol not in adsorbate_elements]]
    all_sites = enumerate_monometallic_sites(atoms, surface=surface, 
                                             heights=heights, subsurf_effect=False)
    random.shuffle(all_sites)    
 
    if True not in atoms.pbc:
        for site in all_sites:
            add_adsorbate(atoms, molecule(adsorbate), site)
    else:
        ads = molecule(adsorbate)[::-1]
        if str(ads.symbols) != 'CO':
            ads.set_chemical_symbols(ads.get_chemical_symbols()[::-1])
        positions = [s['adsorbate_position'] for s in all_sites]
        for pos in positions:
            ads.translate(pos - ads[0].position)
            atoms += ads
        if ads_indices:
            atoms += ads_atoms

    nl = FullNeighborList(rCut=min_adsorbate_distance, atoms=atoms)   
    nl.update(atoms)            
    atom_indices = [a.index for a in atoms if a.symbol == adsorbate[-1]]
    random.shuffle(atom_indices)
    ads_symbols = molecule(adsorbate).get_chemical_symbols()
    n_ads_atoms = len(ads_symbols)
    overlap_atoms_indices = []
    
    for idx in atom_indices:   
        neighbor_indices, _ = nl.get_neighbors(idx)
        overlap = 0
        for i in neighbor_indices:                                                                
            if (atoms[i].symbol in adsorbate_elements) and (i not in overlap_atoms_indices):                     
                overlap += 1                                                                      
        if overlap > 0:                                                                           
            overlap_atoms_indices += list(set([idx-n_ads_atoms+1, idx]))                                
    del atoms[overlap_atoms_indices]

    return atoms