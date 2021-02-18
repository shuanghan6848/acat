"""Adsorbate operators that adds an adsorbate to the surface
of a particle or given structure, using a supplied list of sites."""
from ..settings import adsorbate_elements, adsorbate_molecule, site_heights
from ..utilities import is_list_or_tuple, atoms_too_close_after_addition
from ..adsorption_sites import ClusterAdsorptionSites, SlabAdsorptionSites
from ..adsorbate_coverage import ClusterAdsorbateCoverage, SlabAdsorbateCoverage
from ..build.actions import add_adsorbate_to_site, remove_adsorbate_from_site
from ase.ga.offspring_creator import OffspringCreator
from ase.optimize import BFGS
from ase import Atoms, Atom
from asap3 import FullNeighborList
from asap3 import EMT as asapEMT
from itertools import chain
import numpy as np
import random


class AdsorbateOperator(OffspringCreator):
    """Base class for all operators that add, move or remove adsorbates.

    Don't use this operator directly!"""

    def __init__(self, adsorbate_species, num_muts=1):        
        OffspringCreator.__init__(self, num_muts=num_muts)

        self.adsorbate_species = adsorbate_species if is_list_or_tuple(
                                 adsorbate_species) else [adsorbate_species]

        self.descriptor = 'AdsorbateOperator'

    @classmethod
    def initialize_individual(cls, parent, indi=None):
        indi = OffspringCreator.initialize_individual(parent, indi=indi)
        if 'unrelaxed_adsorbates' in parent.info['data']:
            unrelaxed = list(parent.info['data']['unrelaxed_adsorbates'])
        else:
            unrelaxed = []
        indi.info['data']['unrelaxed_adsorbates'] = unrelaxed
        
        return indi
        
    def get_new_individual(self, parents):
        raise NotImplementedError

    def add_adsorbate(self, atoms, hetero_site_list, 
                      heights, adsorbate_species=None, 
                      min_adsorbate_distance=2., tilt_angle=0.):
        """Adds the adsorbate in self.adsorbate to the supplied atoms
        object at the first free site in the specified site_list. A site
        is free if no other adsorbates can be found in a sphere of radius
        min_adsorbate_distance around the chosen site.

        Parameters:

        atoms: Atoms object
            the atoms object that the adsorbate will be added to

        hetero_site_list: list
            a list of dictionaries, each dictionary should be of the
            following form:
            {'normal': n, 'position': p, 'site': si, 'surface': su}

        min_adsorbate_distance: float
            the radius of the sphere inside which no other
            adsorbates should be found
        
        tilt_angle: float
            Tilt the adsorbate with an angle (in degress) relative to
            the surface normal.
        """
        if not adsorbate_species:
            adsorbate_species=self.adsorbate_species

        i = 0
        too_close = True
        while too_close:
            if i >= len(hetero_site_list):
                return False

            site = hetero_site_list[i]
            if site['occupied']:
                i += 1
                continue

            # Allow only single-atom species to enter subsurf 6fold sites
            site_type = site['site']
            if site_type == '6fold':
                adsorbate_species = [s for s in adsorbate_species if len(s) == 1]

            # Add a random adsorbate to the correct position
            adsorbate = random.choice(adsorbate_species)
            height = heights[site_type]
            add_adsorbate_to_site(atoms, adsorbate, site, height, 
                                  tilt_angle=tilt_angle)

            nads = len(adsorbate)
            ads_atoms = atoms[[a.index for a in atoms if 
                               a.symbol in adsorbate_elements]]
            if atoms_too_close_after_addition(ads_atoms, nads, 
            cutoff=min_adsorbate_distance):
                atoms = atoms[:-nads]
                i += 1
                continue    

            too_close = False 

        # Setting the indices of the unrelaxed adsorbates for the cut-
        # relax-paste function to be executed in the calculation script.
        # There it should also reset the parameter to [], to indicate
        # that the adsorbates have been relaxed.
        ads_indices = sorted([len(atoms) - k - 1 for k in range(len(adsorbate))])
        
        if 'unrelaxed_adsorbates' not in atoms.info['data']:
            atoms.info['data']['unrelaxed_adsorbates'] = []
        atoms.info['data']['unrelaxed_adsorbates'].append(ads_indices)
        
        return atoms

    def remove_adsorbate(self, atoms, hetero_site_list, return_site_index=False):                          
        """Removes an adsorbate from the atoms object at the first occupied
        site in hetero_site_list. If no adsorbates can be found, one will be
        added instead.
        """
        i = 0
        occupied = True
        while occupied:
            site = hetero_site_list[i]
            if not site['occupied']:
                i += 1
                continue

            if i >= len(hetero_site_list):
                if return_site_index:
                    return False
                print('Removal not possible, will add instead')
                return self.add_adsorbate(atoms, hetero_site_list, site_heights)

            # Remove adsorbate from the correct position
            remove_adsorbate_from_site(atoms, site)

            if return_site_index:
                return i

            occupied = False

        return atoms

    def get_all_adsorbate_indices(self, atoms):
        ac = atoms.copy()
        ads_ind = [a.index for a in ac if 
                   a.symbol in adsorbate_elements]
        mbl = 1.5  # max_bond_length
        nl = FullNeighborList(rCut=mbl / 2., atoms=ac)

        adsorbates = []
        while len(ads_ind) != 0:
            i = int(ads_ind[0])
            mol_ind = self._get_indices_in_adsorbate(ac, nl, i)
            for ind in mol_ind:
                if int(ind) in ads_ind:
                    ads_ind.remove(int(ind))
            adsorbates.append(sorted(mol_ind))
        return adsorbates

    def get_adsorbate_indices(self, atoms, position):
        """Returns the indices of the adsorbate at the supplied position"""
        dmin = 1000.
        for a in atoms:
            if a.symbol in adsorbate_elements:
                d = np.linalg.norm(a.position - position)
                if d < dmin:
                    dmin = d
                    ind = a.index

        for ads in self.get_all_adsorbate_indices(atoms):
            if ind in ads:
                return ads[:]
        
    def _get_indices_in_adsorbate(self, atoms, neighborlist,
                                  index, molecule_indices=None):
        """Internal recursive function that help
        determine adsorbate indices"""
        if molecule_indices is None:
            molecule_indices = []
        mi = molecule_indices
        nl = neighborlist
        mi.append(index)
       # neighbors, _ = nl.get_neighbors(index)
        neighbors = nl[index]

        for n in neighbors:
            if int(n) not in mi:
                if atoms[int(n)].symbol in adsorbate_elements:
                    mi = self._get_indices_in_adsorbate(atoms, nl, n, mi)
        return mi


class AddAdsorbate(AdsorbateOperator):
    """
    Use this operator to add adsorbates to the surface.
    The surface is allowed to change during the algorithm run.

    Site and surface preference can be supplied. If both are supplied site
    will be considered first.

    Supplying a tilt angle will tilt the adsorbate with an angle relative
    to the standard perpendicular to the surface
    """
    def __init__(self, adsorbate_species,
                 heights=site_heights,
                 min_adsorbate_distance=2.,
                 surface=None,
                 allow_6fold=False,
                 composition_effect=True,
                 site_preference=None,
                 surface_preference=None,
                 tilt_angle=None,
                 num_muts=1,
                 dmax=2.5):
        AdsorbateOperator.__init__(self, adsorbate_species,
                                   num_muts=num_muts)
        self.descriptor = 'AddAdsorbate'

        self.heights = heights
        self.min_adsorbate_distance = min_adsorbate_distance
        self.surface = surface
        self.allow_6fold = allow_6fold
        self.composition_effect = composition_effect
        self.site_preference = site_preference
        self.surface_preference = surface_preference
        
        self.tilt_angle = tilt_angle or 0.
        self.min_inputs = 1
        self.dmax = dmax

    def get_new_individual(self, parents):
        """Returns the new individual as an atoms object"""
        f = parents[0]

        print('Add')
        indi = self.initialize_individual(f)
        indi.info['data']['parents'] = [f.info['confid']]

        for atom in f:
            indi.append(atom)

        if True in indi.pbc:
            sas = SlabAdsorptionSites(indi, self.surface,
                                      self.allow_6fold,
                                      self.composition_effect)
            sac = SlabAdsorbateCoverage(indi, sas, dmax=self.dmax)
        else:
            sas = ClusterAdsorptionSites(indi, self.allow_6fold, 
                                         self.composition_effect)
            sac = ClusterAdsorbateCoverage(indi, sas, dmax=self.dmax)
        ads_sites = sac.hetero_site_list

        for _ in range(self.num_muts):
            random.shuffle(ads_sites)

            if self.surface_preference is not None:
                def func(x):
                    return x['surface'] == self.surface_preference
                ads_sites.sort(key=func, reverse=True)

            if self.site_preference is not None:
                def func(x):
                    return x['site'] == self.site_preference
                ads_sites.sort(key=func, reverse=True)

            nindi = self.add_adsorbate(indi, ads_sites, self.heights,
                                       self.adsorbate_species,
                                       self.min_adsorbate_distance,
                                       tilt_angle=self.tilt_angle)
            if not nindi:
                break            

            if self.num_muts > 1:
                if True in nindi.pbc:
                    nsac = SlabAdsorbateCoverage(nindi, sas, dmax=self.dmax)
                else:
                    nsac = ClusterAdsorbateCoverage(nindi, sas, dmax=self.dmax)
                ads_sites = nsac.hetero_site_list                          

        return (self.finalize_individual(indi),
                self.descriptor + ': {0}'.format(f.info['confid']))


class RemoveAdsorbate(AdsorbateOperator):
    """This operator removes an adsorbate from the surface. It works
    exactly (but doing the opposite) as the AddAdsorbate operator."""
    def __init__(self, adsorbate_species,
                 surface=None,
                 allow_6fold=False,
                 composition_effect=True,
                 site_preference=None,
                 surface_preference=None,
                 num_muts=1,
                 dmax=2.5):
        AdsorbateOperator.__init__(self, adsorbate_species,
                                   num_muts=num_muts)
        self.descriptor = 'RemoveAdsorbate'

        self.surface = surface
        self.allow_6fold = allow_6fold
        self.composition_effect = composition_effect        
        self.site_preference = site_preference
        self.surface_preference = surface_preference

        self.min_inputs = 1
        self.dmax = dmax

    def get_new_individual(self, parents):
        f = parents[0]

        print('Remove')
        indi = self.initialize_individual(f)
        indi.info['data']['parents'] = [f.info['confid']]

        for atom in f:
            indi.append(atom)

        if True in indi.pbc:
            sas = SlabAdsorptionSites(indi, self.surface,
                                      self.allow_6fold,
                                      self.composition_effect)
            sac = SlabAdsorbateCoverage(indi, sas, dmax=self.dmax)
        else:
            sas = ClusterAdsorptionSites(indi, self.allow_6fold, 
                                         self.composition_effect)
            sac = ClusterAdsorbateCoverage(indi, sas, dmax=self.dmax)
        ads_sites = sac.hetero_site_list

        for _ in range(self.num_muts):
            random.shuffle(ads_sites)

            if self.surface_preference is not None:
                def func(x):
                    return x['surface'] == self.surface_preference
                ads_sites.sort(key=func, reverse=True)

            if self.site_preference is not None:
                def func(x):
                    return x['site'] == self.site_preference
                ads_sites.sort(key=func, reverse=True)

            nindi = self.remove_adsorbate(indi, ads_sites)

            if not nindi:
                break

            if self.num_muts > 1:
                if True in nindi.pbc:
                    nsac = SlabAdsorbateCoverage(nindi, sas, dmax=self.dmax)
                else:
                    nsac = ClusterAdsorbateCoverage(nindi, sas, dmax=self.dmax)
                ads_sites = nsac.hetero_site_list                          

        return (self.finalize_individual(indi),
                self.descriptor + ': {0}'.format(f.info['confid']))


class MoveAdsorbate(AdsorbateOperator):                                           
    """This operator removes an adsorbate from the surface and adds it
    again to a different site, i.e. effectively moving the adsorbate."""
    def __init__(self, adsorbate_species,
                 heights=site_heights,
                 min_adsorbate_distance=2.,
                 surface=None,
                 allow_6fold=False,
                 composition_effect=True,
                 site_preference_from=None,
                 surface_preference_from=None,
                 site_preference_to=None,
                 surface_preference_to=None,
                 tilt_angle=None,
                 num_muts=1,
                 dmax=2.5):
        AdsorbateOperator.__init__(self, adsorbate_species,
                                   num_muts=num_muts)
        self.descriptor = 'MoveAdsorbate'

        self.heights = heights
        self.min_adsorbate_distance = min_adsorbate_distance
        self.surface = surface
        self.allow_6fold = allow_6fold               
        self.composition_effect = composition_effect
        self.site_preference_from = site_preference_from
        self.surface_preference_from = surface_preference_from
        self.site_preference_to = site_preference_to
        self.surface_preference_to = surface_preference_to

        self.tilt_angle = tilt_angle or 0.
        self.min_inputs = 1
        self.dmax = dmax

    def get_new_individual(self, parents):
        f = parents[0]

        print('Move')
        indi = self.initialize_individual(f)
        indi.info['data']['parents'] = [f.info['confid']]

        for atom in f:
            indi.append(atom)

        if True in indi.pbc:
            sas = SlabAdsorptionSites(indi, self.surface,
                                      self.allow_6fold,
                                      self.composition_effect)
            sac = SlabAdsorbateCoverage(indi, sas, dmax=self.dmax)
        else:
            sas = ClusterAdsorptionSites(indi, self.allow_6fold, 
                                         self.composition_effect)
            sac = ClusterAdsorbateCoverage(indi, sas, dmax=self.dmax)
        ads_sites = sac.hetero_site_list

        for _ in range(self.num_muts):
            random.shuffle(ads_sites)
            if self.surface_preference_from is not None:
                def func(x):
                    return x['surface'] == self.surface_preference_from
                ads_sites.sort(key=func, reverse=True)

            if self.site_preference_from is not None:
                def func(x):
                    return x['site'] == self.site_preference_from
                ads_sites.sort(key=func, reverse=True)

            removed = self.remove_adsorbate(indi, ads_sites,
                                            return_site_index=True)
            if not removed:
                break

            removed_species = ads_sites[removed]['adsorbate']            
            random.shuffle(ads_sites)

            if self.surface_preference_to is not None:
                def func(x):
                    return x['surface'] == self.surface_preference_to
                ads_sites.sort(key=func, reverse=True)

            if self.site_preference_to is not None:
                def func(x):
                    return x['site'] == self.site_preference_to
                ads_sites.sort(key=func, reverse=True)

            nindi = self.add_adsorbate(indi, ads_sites, 
                                       self.heights, removed_species,
                                       self.min_adsorbate_distance,
                                       tilt_angle=self.tilt_angle)
            if not nindi:
                break
            
            if self.num_muts > 1:
                if True in nindi.pbc:
                    nsac = SlabAdsorbateCoverage(nindi, sas, dmax=self.dmax)
                else:
                    nsac = ClusterAdsorbateCoverage(nindi, sas, dmax=self.dmax)
                ads_sites = nsac.hetero_site_list                          

        return (self.finalize_individual(indi),
                self.descriptor + ': {0}'.format(f.info['confid']))


class ReplaceAdsorbate(AdsorbateOperator):                                           
    """This operator removes an adsorbate from the surface and adds another
    species to the same site, i.e. effectively replacing the adsorbate."""
    def __init__(self, adsorbate_species,
                 heights=site_heights,
                 min_adsorbate_distance=2.,
                 surface=None,
                 allow_6fold=False,
                 composition_effect=True,
                 site_preference_from=None,
                 surface_preference_from=None,
                 tilt_angle=None,
                 num_muts=1,
                 dmax=2.5):
        AdsorbateOperator.__init__(self, adsorbate_species,
                                   num_muts=num_muts)
        self.descriptor = 'ReplaceAdsorbate'

        self.heights = heights
        self.min_adsorbate_distance = min_adsorbate_distance
        self.surface = surface
        self.allow_6fold = allow_6fold               
        self.composition_effect = composition_effect
        self.site_preference_from = site_preference_from
        self.surface_preference_from = surface_preference_from

        self.tilt_angle = tilt_angle or 0.
        self.min_inputs = 1
        self.dmax = dmax

    def get_new_individual(self, parents):
        f = parents[0]

        print('Replace')
        indi = self.initialize_individual(f)
        indi.info['data']['parents'] = [f.info['confid']]

        for atom in f:
            indi.append(atom)

        if True in indi.pbc:
            sas = SlabAdsorptionSites(indi, self.surface,
                                      self.allow_6fold,
                                      self.composition_effect)
            sac = SlabAdsorbateCoverage(indi, sas, dmax=self.dmax)
        else:
            sas = ClusterAdsorptionSites(indi, self.allow_6fold, 
                                         self.composition_effect)
            sac = ClusterAdsorbateCoverage(indi, sas, dmax=self.dmax)
        ads_sites = sac.hetero_site_list

        for _ in range(self.num_muts):
            random.shuffle(ads_sites)
            if self.surface_preference_from is not None:
                def func(x):
                    return x['surface'] == self.surface_preference_from
                ads_sites.sort(key=func, reverse=True)

            if self.site_preference_from is not None:
                def func(x):
                    return x['site'] == self.site_preference_from
                ads_sites.sort(key=func, reverse=True)

            removed = self.remove_adsorbate(indi, ads_sites,
                                            return_site_index=True)
            if not removed:
                break

            ads_sites[removed]['occupied'] = 0
            removed_species = ads_sites[removed]['adsorbate']
            other_species = [s for s in self.adsorbate_species if
                             s != removed_species]

            nindi = self.add_adsorbate(indi, [ads_sites[removed]], 
                                     self.heights, other_species,
                                     self.min_adsorbate_distance,
                                     tilt_angle=self.tilt_angle)
            if not nindi:
                break
            
            if self.num_muts > 1:
                if True in nindi.pbc:
                    nsac = SlabAdsorbateCoverage(nindi, sas, dmax=self.dmax)
                else:
                    nsac = ClusterAdsorbateCoverage(nindi, sas, dmax=self.dmax)
                ads_sites = nsac.hetero_site_list                          

        return (self.finalize_individual(indi),
                self.descriptor + ': {0}'.format(f.info['confid']))

        
class CutSpliceCrossoverWithAdsorbates(AdsorbateOperator):
    """Crossover that cuts two particles through a plane in space and
    merges two halfes from different particles together.

    Implementation of the method presented in:
    D. M. Deaven and K. M. Ho, Phys. Rev. Lett., 75, 2, 288-291 (1995)

    It keeps the correct composition by randomly assigning elements in
    the new particle. If some of the atoms in the two particle halves
    are too close, the halves are moved away from each other perpendicular
    to the cutting plane.

    Parameters:

    adsorbate: str or Atoms
        specifies the type of adsorbate, it will not be taken into account
        when keeping the correct size and composition

    blmin: dict
        Dictionary of minimum distance between atomic numbers.
        e.g. {(28,29): 1.5}
    
    keep_composition: boolean
        Should the composition be the same as in the parents
    
    rotate_vectors: list
        A list of vectors that the part of the structure that is cut
        is able to rotate around, the size of rotation is set in
        rotate_angles.
        Default None meaning no rotation is performed

    rotate_angles: list
        A list of angles that the structure cut can be rotated. The vector
        being rotated around is set in rotate_vectors.
        Default None meaning no rotation is performed
    """
    def __init__(self, adsorbate_species, blmin, 
                 keep_composition=True,
                 fix_coverage=False, 
                 min_adsorbate_distance=2.,
                 allow_6fold=False, 
                 composition_effect=True,
                 rotate_vectors=None, 
                 rotate_angles=None,
                 dmax=2.5):

        AdsorbateOperator.__init__(self, adsorbate_species)
        self.blmin = blmin
        self.keep_composition = keep_composition
        self.fix_coverage = fix_coverage
        self.min_adsorbate_distance = min_adsorbate_distance
        self.allow_6fold = allow_6fold              
        self.composition_effect = composition_effect
        self.rvecs = rotate_vectors
        self.rangs = rotate_angles
        self.descriptor = 'CutSpliceCrossoverWithAdsorbates'
        
        self.min_inputs = 2
        self.dmax = dmax
        
    def get_new_individual(self, parents):
        f, m = parents

        print('crossover')        
        if self.fix_coverage:
            # Count number of adsorbates
            adsorbates_in_parents = len(self.get_all_adsorbate_indices(f))
            
        indi = self.initialize_individual(f)
        indi.info['data']['parents'] = [i.info['confid'] for i in parents]
        
        fna = self.get_atoms_without_adsorbates(f)
        mna = self.get_atoms_without_adsorbates(m)
        fna_geo_mid = np.average(fna.get_positions(), 0)
        mna_geo_mid = np.average(mna.get_positions(), 0)
        
        if self.rvecs is not None:
            if not isinstance(self.rvecs, list):
                print('Rotation vectors are not a list, skipping rotation')
            else:
                vec = random.choice(self.rvecs)
                try:
                    angle = random.choice(self.rangs)
                except TypeError:
                    angle = self.rangs
                f.rotate(angle, vec, center=fna_geo_mid)
                vec = random.choice(self.rvecs)
                try:
                    angle = random.choice(self.rangs)
                except TypeError:
                    angle = self.rangs
                m.rotate(angle, vec, center=mna_geo_mid)
                
        theta = random.random() * 2 * np.pi  # 0,2pi
        phi = random.random() * np.pi  # 0,pi
        e = np.asarray((np.sin(phi) * np.cos(theta),
                        np.sin(theta) * np.sin(phi),
                        np.cos(phi)))
        eps = 0.0001
        
        # Move each particle to origo with their respective geometrical
        # centers, without adsorbates
        common_mid = (fna_geo_mid + mna_geo_mid) / 2.
        f.translate(-common_mid)
        m.translate(-common_mid)
        
        off = 1
        while off != 0:
            fna = self.get_atoms_without_adsorbates(f)
            mna = self.get_atoms_without_adsorbates(m)

            # Get the signed distance to the cutting plane
            # We want one side from f and the other side from m
            fmap = [np.dot(x, e) for x in fna.get_positions()]
            mmap = [-np.dot(x, e) for x in mna.get_positions()]
            ain = sorted([i for i in chain(fmap, mmap) if i > 0],
                         reverse=True)
            aout = sorted([i for i in chain(fmap, mmap) if i < 0],
                          reverse=True)

            off = len(ain) - len(fna)

            # Translating f and m to get the correct number of atoms
            # in the offspring
            if off < 0:
                # too few
                # move f and m away from the plane
                dist = abs(aout[abs(off) - 1]) + eps
                f.translate(e * dist)
                m.translate(-e * dist)
            elif off > 0:
                # too many
                # move f and m towards the plane
                dist = abs(ain[-abs(off)]) + eps
                f.translate(-e * dist)
                m.translate(e * dist)
            eps /= 5.

        fna = self.get_atoms_without_adsorbates(f)
        mna = self.get_atoms_without_adsorbates(m)
        
        # Determine the contributing parts from f and m
        tmpf, tmpm = Atoms(), Atoms()
        for atom in fna:
            if np.dot(atom.position, e) > 0:
                atom.tag = 1
                tmpf.append(atom)
        for atom in mna:
            if np.dot(atom.position, e) < 0:
                atom.tag = 2
                tmpm.append(atom)

        # Place adsorbates from f and m in tmpf and tmpm
        f_ads = self.get_all_adsorbate_indices(f)
        m_ads = self.get_all_adsorbate_indices(m)
        for ads in f_ads:
            if np.dot(f[ads[0]].position, e) > 0:
                for i in ads:
                    f[i].tag = 1
                    tmpf.append(f[i])
        for ads in m_ads:
            pos = m[ads[0]].position
            if np.dot(pos, e) < 0:
                # If the adsorbate will sit too close to another adsorbate
                # (below self.min_adsorbate_distance) do not add it.
                dists = [np.linalg.norm(pos - a.position)
                         for a in tmpf if a.tag == 1]
                for d in dists:
                    if d < self.min_adsorbate_distance:
                        break
                else:
                    for i in ads:
                        m[i].tag = 2
                        tmpm.append(m[i])
                
        tmpfna = self.get_atoms_without_adsorbates(tmpf)
        tmpmna = self.get_atoms_without_adsorbates(tmpm)
                
        # Check that the correct composition is employed
        if self.keep_composition:
            opt_sm = sorted(fna.numbers)
            tmpf_numbers = list(tmpfna.numbers)
            tmpm_numbers = list(tmpmna.numbers)
            cur_sm = sorted(tmpf_numbers + tmpm_numbers)
            # correct_by: dictionary that specifies how many
            # of the atom_numbers should be removed (a negative number)
            # or added (a positive number)
            correct_by = dict([(j, opt_sm.count(j)) for j in set(opt_sm)])
            for n in cur_sm:
                correct_by[n] -= 1
            correct_in = random.choice([tmpf, tmpm])
            to_add, to_rem = [], []
            for num, amount in correct_by.items():
                if amount > 0:
                    to_add.extend([num] * amount)
                elif amount < 0:
                    to_rem.extend([num] * abs(amount))
            for add, rem in zip(to_add, to_rem):
                tbc = [a.index for a in correct_in if a.number == rem]
                if len(tbc) == 0:
                    pass
                ai = random.choice(tbc)
                correct_in[ai].number = add
                
        # Move the contributing apart if any distance is below blmin
        maxl = 0.
        for sv, min_dist in self.get_vectors_below_min_dist(tmpf + tmpm):
            lsv = np.linalg.norm(sv)  # length of shortest vector
            d = [-np.dot(e, sv)] * 2
            d[0] += np.sqrt(np.dot(e, sv)**2 - lsv**2 + min_dist**2)
            d[1] -= np.sqrt(np.dot(e, sv)**2 - lsv**2 + min_dist**2)
            l = sorted([abs(i) for i in d])[0] / 2. + eps
            if l > maxl:
                maxl = l
        tmpf.translate(e * maxl)
        tmpm.translate(-e * maxl)
        
        # Translate particles halves back to the center
        tmpf.translate(common_mid)
        tmpm.translate(common_mid)

        # Put the two parts together
        for atom in chain(tmpf, tmpm):
            indi.append(atom)

        pcas = ClusterAdsorptionSites(indi, self.allow_6fold, 
                                     self.composition_effect)
        pcac = ClusterAdsorbateCoverage(indi, pcas, dmax=self.dmax)
        pads_sites = pcac.hetero_site_list       
 
       # # Use EMT to pre-optimize the structure 
       # indi = indi[[a.index for a in indi if
       #              a.symbol not in adsorbate_elements]]
       # indi.calc = EMT()
       # opt = BFGS(indi, logfile=None) 
       # opt.run(fmax=0.1)
       # indi.calc = None

        adsi_dict = {}      
        for st in pads_sites:
            if st['occupied']:
                if st['dentate'] > 1:
                    if st['adsorbate_indices'][0] != st['bonding_index']:
                        continue
                si = st['indices']
                adsi_dict[si] = {}
                adsi_dict[si]['height'] = st['bond_length']
                adsi_dict[si]['adsorbate'] = st['adsorbate']
                
        indi = pcas.ref_atoms
        cas = ClusterAdsorptionSites(indi, self.allow_6fold,         
                                     self.composition_effect)
        for st in cas.site_list:
            si = st['indices']
            if si in adsi_dict:
                adsorbate = adsi_dict[si]['adsorbate']
                height = adsi_dict[si]['height']    
                add_adsorbate_to_site(indi, adsorbate, st, height)

        cac = ClusterAdsorbateCoverage(indi, cas, dmax=self.dmax)
        ads_sites = cac.hetero_site_list

        if self.fix_coverage:
            # Remove or add adsorbates as needed
            adsorbates_in_child = self.get_all_adsorbate_indices(indi)
            diff = len(adsorbates_in_child) - adsorbates_in_parents
            if diff < 0:
                # Add adsorbates
                for _ in range(abs(diff)):
                    self.add_adsorbate(indi, ads_sites, site_heights,
                                       self.adsorbate_species,
                                       self.min_adsorbate_distance)
            elif diff > 0:
                # Remove adsorbates
                tbr = random.sample(adsorbates_in_child, diff)  # to be removed
                for adsorbate_indices in sorted(tbr, reverse=True):
                    for i in adsorbate_indices[::-1]:
                        indi.pop(i)

        return (self.finalize_individual(indi),
                self.descriptor + ': {0} {1}'.format(f.info['confid'],
                                                     m.info['confid']))

    def get_numbers(self, atoms):
        """Returns the atomic numbers of the atoms object
        without adsorbates"""
        ac = atoms.copy()
        del ac[[a.index for a in ac
                if a.symbol in adsorbate_elements]]
        return ac.numbers
        
    def get_atoms_without_adsorbates(self, atoms):
        ac = atoms.copy()
        del ac[[a.index for a in ac
                if a.symbol in adsorbate_elements]]
        return ac
        
    def get_vectors_below_min_dist(self, atoms):
        """Generator function that returns each vector (between atoms)
        that is shorter than the minimum distance for those atom types
        (set during the initialization in blmin)."""
        ap = atoms.get_positions()
        an = atoms.numbers
        for i in range(len(atoms)):
            pos = atoms[i].position
            for j, d in enumerate([np.linalg.norm(k - pos) for k in ap[i:]]):
                if d == 0:
                    continue
                min_dist = self.blmin[tuple(sorted((an[i], an[j + i])))]
                if d < min_dist:
                    yield atoms[i].position - atoms[j + i].position, min_dist