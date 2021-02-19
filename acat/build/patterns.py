from ..settings import adsorbate_elements, site_heights  
from ..settings import monodentate_adsorbate_list, multidentate_adsorbate_list
from ..adsorption_sites import ClusterAdsorptionSites, SlabAdsorptionSites
from ..adsorption_sites import group_sites_by_facet
from ..adsorbate_coverage import ClusterAdsorbateCoverage, SlabAdsorbateCoverage
from ..utilities import is_list_or_tuple, get_mic, atoms_too_close_after_addition 
from ..labels import get_cluster_signature_from_label, get_slab_signature_from_label
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
    """`StochasticPatternGenerator` is a class for generating 
    adsorbate coverage patterns stochastically. Graph isomorphism
    is implemented to identify identical coverage patterns.
    4 adsorbate actions are supported: add, remove, move, replace. 
    The function is generalized for both periodic and non-periodic 
    systems (distinguished by atoms.pbc). 

    Parameters
    ----------
    images : ase.Atoms object or list of ase.Atoms objects
        The structure to perform the adsorbate action on. If 
        a list of structures is provided, perform adsorbate 
        action on one of the structures in each step. 
        Accept any ase.Atoms object. No need to be built-in.

    adsorbate_species : str or list of strs 
        A list of adsorbate species to be randomly added to the surface.

    image_probabilities : listt, default None
        A list of the probabilities of selecting each structure.
        Selecting structure with equal probability if not specified.

    species_probabilities : dict, default None
        A dictionary that contains keys of each adsorbate species and 
        values of their probabilities of adding onto the surface.
        Adding adsorbate species with equal probability if not specified.

    min_adsorbate_distance : float, default 1.5
        The minimum distance constraint between two atoms that belongs 
        to two adsorbates.

    adsorption_sites : acat.AdsorptionSites object, default None
        Provide AdsorptionSites object to accelerate the pattern 
        generation. Make sure all the structures have the same 
        periodicity and atom indexing. If composition_effect=True, 
        you should only provide adsorption_sites when the surface 
        composition is fixed.

    surface : str, default None
        The surface type (crystal structure + Miller indices).
        Only required if the structure is a periodic surface slab.

    heights : dict, default acat.settings.site_heights
        A dictionary that contains the adsorbate height for each site 
        type. Use the default height settings if the height for a site 
        type is not specified.

    allow_6fold : bool, default False
        Whether to allow the adsorption on 6-fold subsurf sites 
        beneath fcc hollow sites.

    composition_effect : bool, default False
        Whether to consider sites with different elemental 
        compositions as different sites. It is recommended to 
        set composition=False for monometallics.

    dmax : float, default 2.5
        The maximum bond length (in Angstrom) between the site and the 
        bonding atom  that should be considered as an adsorbate.

    species_forbidden_sites : dict, default None
        A dictionary that contains keys of each adsorbate species and 
        values of the site (can be one or multiple site types) that the 
        speices is not allowed to add to. All sites are availabe for a
        species if not specified. Note that this does not differentiate
        sites with different compositions.

    species_forbidden_labels : dict, default None
        Same as species_forbidden_sites except that the adsorption sites
        are written as numerical labels according to acat.labels. Useful
        when you need to differentiate sites with different compositions.

    fragmentation : bool, default True
        Whether to cut multidentate species into fragments. This ensures 
        that multidentate species with different orientations are
        considered as different coverage patterns.

    trajectory : str, default 'patterns.traj'
        The name of the output ase trajectory file.

    append_trajectory : bool, default False
        Whether to append structures to the existing trajectory. 
        If only unique patterns are accepted, the code will also check 
        graph isomorphism for the existing structures in the trajectory.
        This is also useful when you want to generate coverage patterns 
        stochastically but for all images systematically, e.g. generating
        10 stochastic coverage patterns for each image:
        from acat.build.patterns import StochasticPatternGenerator as SPG
        for atoms in images:
            spg = SPG(atoms, ..., append_trajectory=True)
            spg.run(ngen = 10)

    logfile : str, default 'patterns.log'
        The name of the log file.

    Example
    -------
    The following example illustrates how to generate 100 stochastic
    adsorbate coverage patterns with CO, OH, CH3 and CHO, based on 
    10 Pt fcc111 surface slabs with random C and O coverages, where 
    CH3 is forbidden to be added to ontop and bridge sites:

        >>> from acat.build.patterns import StochasticPatternGenerator as SPG
        >>> from acat.build.patterns import random_coverage_pattern
        >>> from ase.build import fcc111
        >>> slab = fcc111('Pt', (6, 6, 4), 4, vacuum=5.)
        >>> slab.center()
        >>> images = []
        >>> for _ in range(10):
        ...     atoms = slab.copy()
        ...     image = random_coverage_pattern(atoms, adsorbate_species=['C','O'],
        ...                                     surface='fcc111',
        ...                                     min_adsorbate_distance=5.)
        ...     images.append(image)
        >>> spg = SPG(images, adsorbate_species=['CO','OH','CH3','CHO'],
        ...           species_probabilities={'CO':0.3, 'OH': 0.3, 
        ...                                  'CH3': 0.2, 'CHO': 0.2},
        ...           min_adsorbate_distance=1.5, 
        ...           surface='fcc111',
        ...           composition_effect=False, 
        ...           species_forbidden_sites={'CH3': ['ontop','bridge']})
        >>> spg.run(n_gen=100, action='add')
        [movie]

    """

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
                 species_forbidden_sites=None,    
                 species_forbidden_labels=None,
                 fragmentation=True,
                 trajectory='patterns.traj',
                 append_trajectory=False,
                 logfile='patterns.log'):

        self.images = images if is_list_or_tuple(images) else [images]                     
        self.adsorbate_species = adsorbate_species if is_list_or_tuple(
                                 adsorbate_species) else [adsorbate_species]
        self.monodentate_adsorbates = [s for s in self.adsorbate_species if s in 
                                       monodentate_adsorbate_list]
        self.multidentate_adsorbates = [s for s in self.adsorbate_species if s in
                                        multidentate_adsorbate_list]
        if len(self.adsorbate_species) != len(self.monodentate_adsorbates +
        self.multidentate_adsorbates):
            diff = list(set(self.adsorbate_species) - 
                        set(self.monodentate_adsorbates +
                            self.multidentate_adsorbates))
            raise ValueError('species {} are not defined '.format(diff) +
                             'in adsorbate_list in acat.settings')             

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
        self.heights = site_heights
        for k, v in heights.items():
            self.heights[k] = v

        self.dmax = dmax
        self.species_forbidden_sites = species_forbidden_sites
        self.species_forbidden_labels = species_forbidden_labels

        if self.species_forbidden_labels is not None:
            self.species_forbidden_labels = {k: v if is_list_or_tuple(v) else [v] for
                                             k, v in self.species_forbidden_labels.items()}
        if self.species_forbidden_sites is not None:
            self.species_forbidden_sites = {k: v if is_list_or_tuple(v) else [v] for
                                            k, v in self.species_forbidden_sites.items()}  
        self.fragmentation = fragmentation
        if isinstance(trajectory, str):            
            self.trajectory = trajectory 
        self.append_trajectory = append_trajectory
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
                                                                                             
        # Select adsorbate with probability 
        if not self.species_probabilities:
            adsorbate = random.choice(self.adsorbate_species)
        else: 
            adsorbate = random.choices(k=1, population=self.adsorbate_species,
                                       weights=self.species_probability_list)[0]    
                                                                                             
        # Only add one adsorabte to a site at least 2 shells 
        # away from currently occupied sites
        nsids = [i for i, s in enumerate(hsl) if i not in nbstids]

        if self.species_forbidden_labels is not None:
            if adsorbate in self.species_forbidden_labels:
                forb_labs = self.species_forbidden_labels[adsorbate]
                if True in self.atoms.pbc:
                    def get_label(site):
                        if sas.composition_effect:
                            signature = [site['site'], site['geometry'], 
                                         site['composition']]
                        else:
                            signature = [site['site'], site['geometry']]
                        return sas.label_dict['|'.join(signature)]                        
                else:
                    def get_label(site):
                        if sas.composition_effect:
                            signature = [site['site'], site['surface'], 
                                         site['composition']]
                        else:
                            signature = [site['site'], site['surface']]
                        return sas.label_dict['|'.join(signature)]                   

                nsids = [i for i in nsids if get_label(hsl[i]) not in forb_labs]    

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
        else:
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
                forb_labs = self.species_forbidden_labels[adsorbate]
                if True in self.atoms.pbc:
                    def get_label(site):
                        if sas.composition_effect:
                            signature = [site['site'], site['geometry'], 
                                         site['composition']]
                        else:
                            signature = [site['site'], site['geometry']]
                        return sas.label_dict['|'.join(signature)]                        
                else:
                    def get_label(site):
                        if sas.composition_effect:
                            signature = [site['site'], site['surface'], 
                                         site['composition']]
                        else:
                            signature = [site['site'], site['surface']]
                        return sas.label_dict['|'.join(signature)]                   
                                                                                             
                nsids = [i for i in nsids if get_label(hsl[i]) not in forb_labs]   

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

        # Select a different adsorbate with probability 
        old_adsorbate = rpst['adsorbate']
        new_options = [a for a in self.adsorbate_species if a != old_adsorbate]

        if self.species_forbidden_labels is not None:
            _new_options = []
            for o in new_options:
                if o in self.species_forbidden_labels: 
                    if True in self.atoms.pbc:
                        if sas.composition_effect:
                            signature = [rpst['site'], rpst['geometry'], 
                                         rpst['composition']]
                        else:
                            signature = [rpst['site'], rpst['geometry']]
                        lab = sas.label_dict['|'.join(signature)]                        
                                                                                                 
                    else:
                        if sas.composition_effect:
                            signature = [rpst['site'], rpst['surface'], 
                                         rpst['composition']]
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
                                       weights=new_probabilities)[0] 
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
 
    '''unique: whether discard duplicates based on isomorphism or not'''
    def run(self, n_gen, 
            actions=['add','remove','move'], 
            action_probabilities=None,
            unique=True):
 
        mode = 'a' if self.append_trajectory else 'w'
        self.traj = Trajectory(self.trajectory, mode=mode)
        actions = actions if is_list_or_tuple(actions) else [actions]
        if action_probabilities is not None:
            all_action_probabilities = [action_probabilities[a] for a in actions]
        
        self.labels_list, self.graph_list = [], []

        self.unique = unique
        if self.unique and self.append_trajectory:                                 
            if self.logfile is not None:                             
                self.logfile.write('Loading graphs for existing structures in ' +
                                   '{}. This might take a while.\n'.format(self.trajectory))
                self.logfile.flush()

            prev_images = read(self.trajectory, index=':')
            for patoms in prev_images:
                if self.adsorption_sites is not None:
                    psas = self.adsorption_sites
                elif True in patoms.pbc:
                    if self.surface is None:
                        raise ValueError('please specify the surface type')
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
            # Select image with probability 
            if not self.species_probabilities:
                self.atoms = random.choice(self.images).copy()
            else: 
                self.atoms = random.choices(k=1, population=self.images, 
                                            weights=self.image_probabilities)[0].copy()
            self.n_image = n_new 
            if self.adsorption_sites is not None:
                sas = self.adsorption_sites
            elif True in self.atoms.pbc:
                if self.surface is None:
                    raise ValueError('please specify the surface type')
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
                                            weights=all_action_probabilities)[0] 
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
            self.traj.write(self.atoms)
            n_new += 1


class SystematicPatternGenerator(object):
    """`SystematicPatternGenerator` is a class for generating 
    adsorbate coverage patterns systematically. This is useful to 
    enumerate all unique patterns at low coverage, but explodes at
    higher coverages. Graph isomorphism is implemented to identify 
    identical coverage patterns. 4 adsorbate actions are supported: 
    add, remove, move, replace. The function is generalized for both
    periodic and non-periodic systems (distinguished by atoms.pbc). 

    Parameters
    ----------
    images : ase.Atoms object or list of ase.Atoms objects
        The structure to perform the adsorbate action on. If 
        a list of structures is provided, perform adsorbate 
        action on one of the structures in each step. 
        Accept any ase.Atoms object. No need to be built-in.

    adsorbate_species : str or list of strs 
        A list of adsorbate species to be randomly added to the surface.

    min_adsorbate_distance : float, default 1.5
        The minimum distance constraint between two atoms that belongs 
        to two adsorbates.

    adsorption_sites : acat.AdsorptionSites object, default None
        Provide AdsorptionSites object to accelerate the pattern 
        generation. Make sure all the structures have the same 
        periodicity and atom indexing. If composition_effect=True, 
        you should only provide adsorption_sites when the surface 
        composition is fixed.

    surface : str, default None
        The surface type (crystal structure + Miller indices).
        Only required if the structure is a periodic surface slab.

    heights : dict, default acat.settings.site_heights
        A dictionary that contains the adsorbate height for each site 
        type. Use the default height settings if the height for a site 
        type is not specified.

    allow_6fold : bool, default False
        Whether to allow the adsorption on 6-fold subsurf sites 
        beneath fcc hollow sites.

    composition_effect : bool, default False
        Whether to consider sites with different elemental 
        compositions as different sites. It is recommended to 
        set composition=False for monometallics.

    dmax : float, default 2.5
        The maximum bond length (in Angstrom) between the site and the 
        bonding atom  that should be considered as an adsorbate.

    species_forbidden_sites : dict, default None
        A dictionary that contains keys of each adsorbate species and 
        values of the site (can be one or multiple site types) that the 
        speices is not allowed to add to. All sites are availabe for a
        species if not specified. Note that this does not differentiate
        sites with different compositions.

    species_forbidden_labels : dict, default None
        Same as species_forbidden_sites except that the adsorption sites
        are written as numerical labels according to acat.labels. Useful
        when you need to differentiate sites with different compositions.

    enumerate_orientations: bool, default True
        Whether to enumerate all orientations of multidentate species.
        This ensures that multidentate species with different orientations 
        are all enumerated.

    trajectory : str, default 'patterns.traj'
        The name of the output ase trajectory file.

    append_trajectory : bool, default False
        Whether to append structures to the existing trajectory. 
        If only unique patterns are accepted, the code will also check 
        graph isomorphism for the existing structures in the trajectory.
        This is also useful when you want to generate coverage patterns 
        stochastically but for all images systematically, e.g. generating
        10 stochastic coverage patterns for each image:
        from acat.build.patterns import StochasticPatternGenerator as SPG
        for atoms in images:
            spg = SPG(atoms, ..., append_trajectory=True)
            spg.run(ngen = 10)

    logfile : str, default 'patterns.log'
        The name of the log file.

    Example
    -------
    The following example illustrates how to add CO to all unique sites on 
    a cuboctahedral bimetallic nanoparticle:

        >>> from acat.adsorption_sites import ClusterAdsorptionSites
        >>> from acat.build.patterns import SystematicPatternGenerator as SPG
        >>> from ase.cluster import Octahedron
        >>> atoms = Octahedron('Cu', length=7, cutoff=3)
        >>> for atom in atoms:
        ...     if atom.index % 2 == 0:
        ...         atom.symbol = 'Au' 
        >>> atoms.center(vacuum=5.)
        >>> cas = ClusterAdsorptionSites(atoms, composition_effect=True)
        >>> spg = SPG(atoms, adsorbate_species='CO',
        ...           min_adsorbate_distance=2., 
        ...           adsorption_sites=cas,
        ...           composition_effect=True) 
        >>> spg.run(action='add')
        [movie]

    """

    def __init__(self, images,                                                     
                 adsorbate_species,
                 min_adsorbate_distance=1.5,
                 adsorption_sites=None,
                 surface=None,
                 heights=site_heights,
                 allow_6fold=False,
                 composition_effect=True,
                 dmax=2.5,
                 species_forbidden_sites=None,
                 species_forbidden_labels=None,
                 enumerate_orientations=True,
                 trajectory='patterns.traj',
                 append_trajectory=False,
                 logfile='patterns.log'):

        self.images = images if is_list_or_tuple(images) else [images]                     
        self.adsorbate_species = adsorbate_species if is_list_or_tuple(
                                 adsorbate_species) else [adsorbate_species]
        self.monodentate_adsorbates = [s for s in self.adsorbate_species if s in 
                                       monodentate_adsorbate_list]
        self.multidentate_adsorbates = [s for s in self.adsorbate_species if s in
                                        multidentate_adsorbate_list]
        if len(self.adsorbate_species) != len(self.monodentate_adsorbates +
        self.multidentate_adsorbates):
            diff = list(set(self.adsorbate_species) - 
                        set(self.monodentate_adsorbates +
                            self.multidentate_adsorbates))
            raise ValueError('species {} is not defined '.format(diff) +
                             'in adsorbate_list in acat.settings')             

        self.min_adsorbate_distance = min_adsorbate_distance
        self.adsorption_sites = adsorption_sites
        self.surface = surface
        self.heights = site_heights
        for k, v in heights.items():
            self.heights[k] = v

        self.dmax = dmax
        self.species_forbidden_sites = species_forbidden_sites
        self.species_forbidden_labels = species_forbidden_labels
                                                                                           
        if self.species_forbidden_labels is not None:
            self.species_forbidden_labels = {k: v if is_list_or_tuple(v) else [v] for
                                             k, v in self.species_forbidden_labels.items()}
        if self.species_forbidden_sites is not None:
            self.species_forbidden_sites = {k: v if is_list_or_tuple(v) else [v] for
                                            k, v in self.species_forbidden_sites.items()}
        self.enumerate_orientations = enumerate_orientations
        if isinstance(trajectory, str):
            self.trajectory = trajectory                        
        self.append_trajectory = append_trajectory
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

    def _add_adsorbate_enumeration(self, adsorption_sites):
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
                                signature = [nst['site'], nst['geometry'], 
                                             nst['composition']]
                            else:
                                signature = [nst['site'], nst['geometry']]
                            lab = sas.label_dict['|'.join(signature)]                        
                        else:
                            if sas.composition_effect:
                                signature = [nst['site'], nst['surface'], 
                                             nst['composition']]
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
                    self.traj.write(atoms)
                    self.n_write += 1
                    self.n_write_per_image += 1
                    if self.max_gen_per_image is not None:
                        if self.n_write_per_image == self.max_gen_per_image:
                            return

    def _remove_adsorbate_enumeration(self, adsorption_sites):
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
            self.traj.write(atoms)
            self.n_write += 1
            self.n_write_per_image += 1
            if self.max_gen_per_image is not None:
                if self.n_write_per_image == self.max_gen_per_image:
                    return

    def _move_adsorbate_enumeration(self, adsorption_sites): 
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
                                signature = [nst['site'], nst['geometry'], 
                                             nst['composition']]
                            else:
                                signature = [nst['site'], nst['geometry']]
                            lab = sas.label_dict['|'.join(signature)]                        
                        else:
                            if sas.composition_effect:
                                signature = [nst['site'], nst['surface'], 
                                             nst['composition']]
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
                    self.traj.write(final_atoms)
                    self.n_write += 1
                    self.n_write_per_image += 1
                    if self.max_gen_per_image is not None:
                        if self.n_write_per_image == self.max_gen_per_image:
                            return

    def _replace_adsorbate_enumeration(self, adsorption_sites):
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
                                                                                             
            # Select a different adsorbate with probability 
            old_adsorbate = rpst['adsorbate']
            new_options = [a for a in self.adsorbate_species if a != old_adsorbate]

            if self.species_forbidden_labels is not None:
                _new_options = []
                for o in new_options:
                    if o in self.species_forbidden_labels: 
                        if True in atoms.pbc:
                            if sas.composition_effect:
                                signature = [rpst['site'], rpst['geometry'], 
                                             rpst['composition']]
                            else:
                                signature = [rpst['site'], rpst['geometry']]
                            lab = sas.label_dict['|'.join(signature)]                        
                                                                                                 
                        else:
                            if sas.composition_effect:
                                signature = [rpst['site'], rpst['surface'], 
                                             rpst['composition']]
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
                    self.traj.write(final_atoms)
                    self.n_write += 1
                    self.n_write_per_image += 1
                    if self.max_gen_per_image is not None:
                        if self.n_write_per_image == self.max_gen_per_image:
                            return

    def run(self, max_gen_per_image=None, action='add', unique=True):

        mode = 'a' if self.append_trajectory else 'w'
        self.traj = Trajectory(self.trajectory, mode=mode)          
        self.max_gen_per_image = max_gen_per_image
        self.n_write = 0
        self.n_duplicate = 0
        self.labels_list, self.graph_list = [], []

        self.unique = unique
        if self.unique and self.append_trajectory:                                 
            if self.logfile is not None:                             
                self.logfile.write('Loading graphs for existing structures in ' +
                                   '{}. This might take a while.\n'.format(self.trajectory))
                self.logfile.flush()
                                                                                   
            prev_images = read(self.trajectory, index=':')
            for patoms in prev_images:
                if self.adsorption_sites is not None:
                    psas = self.adsorption_sites
                elif True in patoms.pbc:
                    if self.surface is None:
                        raise ValueError('please specify the surface type')
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
            self.n_write_per_image = 0
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
                    raise ValueError('please specify the surface type')
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
                self._add_adsorbate_enumeration(sas)
            elif action == 'remove':
                self._remove_adsorbate_enumeration(sas)
            elif action == 'move':
                self._move_adsorbate_enumeration(sas)
            elif action == 'replace':
                self._replace_adsorbate_enumeration(sas)

            if self.logfile is not None:
                method = 'label match' if self.clean_slab else 'isomorphism'
                self.logfile.write('All possible patterns were generated '
                                   + 'for image {}\n'.format(n) +
                                   '{} patterns were '.format(self.n_duplicate)
                                   + 'discarded by {}\n\n'.format(method))
                self.logfile.flush()


def symmetric_coverage_pattern(atoms, adsorbate, coverage=1., 
                               surface=None, height=None, 
                               min_adsorbate_distance=0.):
    """A function for generating representative symmetric adsorbate 
    coverage patterns. The function is generalized for both periodic 
    and non-periodic systems (distinguished by atoms.pbc).

    Parameters
    ----------
    atoms : ase.Atoms object
        The nanoparticle or surface slab onto which the adsorbates are
        added. Accept any ase.Atoms object. No need to be built-in.

    adsorbate : str or ase.Atom object or ase.Atoms object
        The adsorbate species to be added onto the surface. 
        For now only support adding one type of adsorbate species.

    coverage : float, default 1. 
        The coverage (ML) of the adsorbate (N_adsorbate / N_surf_atoms). 
        Support 4 coverage patterns (0.25 for p(2x2) pattern; 
        0.5 for c(2x2) pattern on fcc100 or honeycomb pattern on fcc111; 
        0.75 for (2x2) pattern on fcc100 or Kagome pattern on fcc111; 
        1 for p(1x1) pattern.
        Note that for small nanoparticles, the function might give 
        results that do not correspond to the coverage. This is normal 
        since the surface area can be too small to encompass the 
        coverage pattern properly. We expect this function to work 
        well on large nanoparticles and surface slabs.                  

    surface : str, default None
        The surface type (crystal structure + Miller indices).
        For now only support 2 common surfaces: fcc100 and fcc111. 
        If the structure is a periodic surface slab, this is required. 
        If the structure is a nanoparticle, the function only add 
        adsorbates to the sites on the specified surface. 

    height : float, default None
        The height of the added adsorbate from the surface.
        Use the default settings if not specified.

    min_adsorbate_distance : float, default 0.
        The minimum distance between two atoms that belongs to two 
        adsorbates.
    
    Example
    -------
    To add a 0.5 ML CO coverage pattern on a cuboctahedron:

        >>> from acat.build.patterns import symmetric_coverage_pattern
        >>> from ase.cluster import Octahedron
        >>> from ase.visualize import view
        >>> atoms = Octahedron('Au', length=9, cutoff=4)
        >>> atoms.center(vacuum=5.)
        >>> pattern = symmetric_coverage_pattern(atoms, adsorbate='CO', 
        ...                                      coverage=0.5)
        >>> view(pattern)
        [image]

    To add a 0.75 ML CO coverage pattern on a fcc111 surface slab:

        >>> from acat.build.patterns import symmetric_coverage_pattern
        >>> from ase.build import fcc111
        >>> from ase.visualize import view
        >>> atoms = fcc111('Cu', (8, 8, 4), vacuum=5.)
        >>> atoms.center()
        >>> pattern = symmetric_coverage_pattern(atoms, adsorbate='CO',
        ...                                      coverage=0.5, 
        ...                                      surface='fcc111')
        >>> view(pattern)
        [image]

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

    #TODO: implement Woods' notation
    final_sites = []
    if 'fcc111' in surface: 
        # p(1x1) pattern
        if coverage == 1:
            fcc_sites = [s for s in site_list 
                         if s['site'] == 'fcc']
            if fcc_sites:
                final_sites += fcc_sites

        # Kagome pattern
        elif coverage == 3/4:
            fcc_sites = [s for s in site_list  
                         if s['site'] == 'fcc']
            if True not in atoms.pbc:                                
                grouped_sites = group_sites_by_facet(atoms, fcc_sites, site_list)
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

        # Honeycomb pattern
        elif coverage == 2/4:
            fcc_sites = [s for s in site_list if s['site'] == 'fcc']
            hcp_sites = [s for s in site_list if s['site'] == 'hcp']
            all_sites = fcc_sites + hcp_sites
            if True not in atoms.pbc:    
                grouped_sites = group_sites_by_facet(atoms, all_sites, site_list)
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

        # p(2x2) pattern
        elif coverage == 1/4:
            fcc_sites = [s for s in site_list 
                         if s['site'] == 'fcc']                                                                 
            if True not in atoms.pbc:                                
                grouped_sites = group_sites_by_facet(atoms, fcc_sites, site_list)
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
        # p(1x1) pattern
        if coverage == 1:
            fold4_sites = [s for s in site_list if s['site'] == '4fold']
            if fold4_sites:
                final_sites += fold4_sites

        # (2x2) pattern 
        elif coverage == 3/4:
            fold4_sites = [s for s in site_list if s['site'] == '4fold']
            if True not in atoms.pbc:                                           
                grouped_sites = group_sites_by_facet(atoms, fold4_sites, site_list)
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

        # c(2x2) pattern
        elif coverage == 2/4:
            fold4_sites = [s for s in site_list if s['site'] == '4fold']
            original_sites = deepcopy(fold4_sites)
            if True not in atoms.pbc:
                grouped_sites = group_sites_by_facet(atoms, fold4_sites, site_list)
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

        # p(2x2) pattern
        elif coverage == 1/4:
            fold4_sites = [s for s in site_list if s['site'] == '4fold']
            if True not in atoms.pbc:                                           
                grouped_sites = group_sites_by_facet(atoms, fold4_sites, site_list)
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
    """A function for generating different p(1x1) adsorbate coverage 
    patterns. The function is generalized for both periodic and 
    non-periodic systems (distinguished by atoms.pbc).

    Parameters
    ----------
    atoms : ase.Atoms object
        The nanoparticle or surface slab onto which the adsorbates are
        added. Accept any ase.Atoms object. No need to be built-in.

    adsorbate : str or ase.Atom object or ase.Atoms object
        The adsorbate species to be added onto the surface.
        For now only support adding one type of adsorbate species.

    site : str
        The site type that the adsorbates should be added to.

    surface : str, default None
        The surface type (crystal structure + Miller indices). 
        If the structure is a periodic surface slab, this is required. 
        If the structure is a nanoparticle, the function only add 
        adsorbates to the sites on the specified surface. 

    height : float, default None
        The height of the added adsorbate from the surface.
        Use the default settings if not specified.

    min_adsorbate_distance : float, default 0.
        The minimum distance between two atoms that belongs to two 
        adsorbates.
    
    Example
    -------
    To add a 1 ML CO coverage pattern to the hcp sites on a icosahedron:

        >>> from acat.build.patterns import full_coverage_pattern
        >>> from ase.cluster import Icosahedron
        >>> from ase.visualize import view
        >>> atoms = Icosahedron('Au', noshells=5)
        >>> atoms.center(vacuum=5.)
        >>> pattern = full_coverage_pattern(atoms, adsorbate='CO', site='hcp')
        >>> view(pattern)
        [image]

    To add a 1 ML CO coverage pattern to the 3fold sites on a bcc110 
    surface slab:

        >>> from acat.build.patterns import full_coverage_pattern
        >>> from ase.build import bcc110
        >>> from ase.visualize import view
        >>> atoms = bcc110('Mo', (8, 8, 4), vacuum=5.)
        >>> atoms.center()
        >>> pattern = full_coverage_pattern(atoms, adsorbate='CO',
        ...                                 surface='bcc110', site='3fold')
        >>> view(pattern)
        [image]

    """

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
                            species_probabilities=None,
                            surface=None, 
                            min_adsorbate_distance=1.5, 
                            heights=site_heights,
                            allow_6fold=False):
    """A function for generating random coverage patterns with a 
    minimum distance constraint. The function is generalized for 
    both periodic and non-periodic systems (distinguished by 
    atoms.pbc).

    Parameters
    ----------
    atoms : ase.Atoms object
        The nanoparticle or surface slab onto which the adsorbates are
        added. Accept any ase.Atoms object. No need to be built-in.

    adsorbate_species : str or list of strs 
        A list of adsorbate species to be randomly added to the surface.

    species_probabilities : dict, default None
        A dictionary that contains keys of each adsorbate species and 
        values of their probabilities of adding onto the surface.

    surface : str, default None
        The surface type (crystal structure + Miller indices).
        If the structure is a periodic surface slab, this is required. 
        If the structure is a nanoparticle, the function only add 
        adsorbates to the sites on the specified surface. 

    heights : dict, default acat.settings.site_heights
        A dictionary that contains the adsorbate height for each site 
        type. Use the default height settings if the height for a site 
        type is not specified.

    min_adsorbate_distance : float, default 1.5
        The minimum distance constraint between two atoms that belongs 
        to two adsorbates.

    allow_6fold : bool, default False
        Whether to allow the adsorption on 6-fold subsurf sites 
        beneath fcc hollow sites.
    
    Example
    -------
    To add CO randomly onto a cuboctahedron with a minimum adsorbate 
    distance of 5 Angstrom:

        >>> from acat.build.patterns import random_coverage_pattern
        >>> from ase.cluster import Octahedron
        >>> from ase.visualize import view
        >>> atoms = Octahedron('Au', length=9, cutoff=4)
        >>> atoms.center(vacuum=5.)
        >>> pattern = random_coverage_pattern(atoms, adsorbate_species='CO', 
        ...                                   min_adsorbate_distance=5.)
        >>> view(pattern)
        [image]

    To add C, N, O randomly onto a hcp0001 surface slab with probabilities 
    of 0.25, 0.25, 0.5, respectively, and a minimum adsorbate distance of 
    2 Angstrom:

        >>> from acat.build.patterns import random_coverage_pattern
        >>> from ase.build import hcp0001
        >>> from ase.visualize import view
        >>> atoms = hcp0001('Ru', (8, 8, 4), vacuum=5.)
        >>> atoms.center()
        >>> pattern = random_coverage_pattern(atoms, adsorbate_species=['C','N','O'],
        ...                                   species_probabilities={'C': 0.25, 
        ...                                                          'N': 0.25, 
        ...                                                          'O': 0.5},
        ...                                   surface='hcp0001',
        ...                                   min_adsorbate_distance=2.)
        >>> view(pattern)
        [image]

    """
    adsorbate_species = adsorbate_species if is_list_or_tuple(
                        adsorbate_species) else [adsorbate_species]
    if species_probabilities is not None:
        assert len(species_probabilities.keys()) == len(adsorbate_species)
        probability_list = [species_probabilities[a] for a in adsorbate_species]               
    
    _heights = site_heights
    for k, v in heights.items():
        _heights[k] = v
    heights = _heights
 
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
        # Select adsorbate with probability 
        if not species_probabilities:
            adsorbate = random.choice(adsorbate_species)
        else: 
            adsorbate = random.choices(k=1, population=adsorbate_species,
                                       weights=probability_list)[0] 
        nads = nads_dict[adsorbate] 
        height = heights[st['site']]
        add_adsorbate_to_site(atoms, adsorbate, st, height)       
        if min_adsorbate_distance > 0:
            if atoms_too_close_after_addition(atoms[natoms:], nads,
            min_adsorbate_distance, mic=(True in atoms.pbc)):
                atoms = atoms[:-nads]                               

    return atoms
