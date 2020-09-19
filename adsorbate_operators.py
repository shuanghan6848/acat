"""Adsorbate operators that adds an adsorbate to the surface
of a particle or given structure, using a supplied list of sites."""
import numpy as np
import random
from itertools import chain
from ase import Atoms, Atom
from ase.build import molecule
from ase.ga.offspring_creator import OffspringCreator
from ase.neighborlist import NeighborList, natural_cutoffs
from .adsorption_sites import get_mic_distance, enumerate_monometallic_sites


adsorbates = 'SCHON'


class AdsorbateOperator(OffspringCreator):
    """Base class for all operators that add, move or remove adsorbates.

    Don't use this operator directly!"""

    def __init__(self, adsorbate, num_muts=1):        
        OffspringCreator.__init__(self, num_muts=num_muts)
        self.adsorbate = self.convert_adsorbate(adsorbate)
        self.adsorbate_set = set(self.adsorbate.get_chemical_symbols())
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

    def add_adsorbate(self, atoms, sites_list,
                      min_adsorbate_distance=1.5, tilt_angle=0.):
        """Adds the adsorbate in self.adsorbate to the supplied atoms
        object at the first free site in the specified sites_list. A site
        is free if no other adsorbates can be found in a sphere of radius
        min_adsorbate_distance around the chosen site.

        Parameters:

        atoms: Atoms object
            the atoms object that the adsorbate will be added to

        sites_list: list
            a list of dictionaries, each dictionary should be of the
            following form:
            {'height': h, 'normal': n, 'adsorbate_position': ap,
            'site': si, 'surface': su}

        min_adsorbate_distance: float
            the radius of the sphere inside which no other
            adsorbates should be found
        
        tilt_angle: float
            Tilt the adsorbate with an angle (in degress) relative to
            the surface normal.
        """
        i = 0
        while self.is_site_occupied(atoms, sites_list[i],
                                    min_adsorbate_distance):
            i += 1
            if i >= len(sites_list):
                return False
        site = sites_list[i]

        # Make the correct position
        height = site['height']
        normal = np.array(site['normal'])
        pos = np.array(site['adsorbate_position']) + normal * height

        # Rotate the adsorbate according to the normal
        ads = self.adsorbate.copy()
        if len(ads) > 1:
            avg_pos = np.average(ads[1:].positions, 0)
            ads.rotate(avg_pos - ads[0].position, normal)
            pvec = np.cross(np.random.rand(3) - ads[0].position, normal)
            ads.rotate(tilt_angle, pvec, center=ads[0].position)
        ads.translate(pos - ads[0].position)

        atoms.extend(ads)
        
        # Setting the indices of the unrelaxed adsorbates for the cut-
        # relax-paste function to be executed in the calculation script.
        # There it should also reset the parameter to [], to indicate
        # that the adsorbates have been relaxed.
        ads_indices = sorted([len(atoms) - k - 1 for k in range(len(ads))])
        atoms.info['data']['unrelaxed_adsorbates'].append(ads_indices)
        
        # site['occupied'] = 1

        return True

    def remove_adsorbate(self, atoms, sites_list, for_move=False):
        """Removes an adsorbate from the atoms object at the first occupied
        site in sites_list. If no adsorbates can be found, one will be
        added instead.
        """
        i = 0
        while not self.is_site_occupied(atoms, sites_list[i],
                                        min_adsorbate_distance=0.2):
            # very small min_adsorbate_distance used for testing
            i += 1
            if i >= len(sites_list):
                if for_move:
                    return False
                print('removal not possible will add instead')
                return self.add_adsorbate(atoms, sites_list)
        # sites_list[i]['occupied'] = 0
        site = sites_list[i]

        # Make the correct position
        height = site['height']
        normal = np.array(site['normal'])
        pos = np.array(site['adsorbate_position']) + normal * height

        ads_ind = self.get_adsorbate_indices(atoms, pos)
        ads_ind.sort(reverse=True)

        len_ads = len(self.adsorbate)
        if len(ads_ind) != len_ads:
            print('removing other than {0}'.format(len_ads), ads_ind, pos)
            print(atoms.info)
            random.shuffle(sites_list)
            return self.remove_adsorbate(atoms, sites_list, for_move=for_move)
        # print('removing', ads_ind, [atoms[j].symbol for j in ads_ind], pos)
        for k in ads_ind:
            atoms.pop(k)

        return True

    def get_all_adsorbate_indices(self, atoms):
        ac = atoms.copy()
        ads_ind = [a.index for a in ac
                   if a.symbol in self.adsorbate_set]
        mbl = 1.5  # max_bond_length
        nl = NeighborList([mbl / 2. for i in ac],
                             skin=0.0, self_interaction=False)
        nl.update(ac)

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
            if a.symbol in self.adsorbate_set:
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
        neighbors, _ = nl.get_neighbors(index)
        for n in neighbors:
            if int(n) not in mi:
                if atoms[int(n)].symbol in self.adsorbate_set:
                    mi = self._get_indices_in_adsorbate(atoms, nl, n, mi)
        return mi

    def is_site_occupied(self, atoms, site, min_adsorbate_distance):
        """Returns True if the site on the atoms object is occupied by
        creating a sphere of radius min_adsorbate_distance and checking
        that no other adsorbate is inside the sphere."""
        # if site['occupied']:
        #     return True
        if True not in atoms.get_pbc():
            ads = self.adsorbate_set
            height = site['height']
            normal = np.array(site['normal'])
            pos = np.array(site['adsorbate_position']) + normal * height
            dists = [np.linalg.norm(pos - a.position)
                     for a in atoms if a.symbol in ads]
            for d in dists:
                if d < min_adsorbate_distance:
                    # print('under min d', d, pos)
                    # site['occupied'] = 1
                    return True
            return False
        else:
            ads = self.adsorbate_set
            cell = atoms.get_cell()
            pbc = np.array([cell[0][0], cell[1][1], 0])
            pos = np.array(site['adsorbate_position'])
            dists = [get_mic_distance(pos, a.position, atoms) 
                     for a in atoms if a.symbol in ads]
            for d in dists:
                if d < min_adsorbate_distance:
                    # print('under min d', d, pos)
                    # site['occupied'] = 1
                    return True
            return False


    def is_site_occupied_by(self, atoms, adsorbate, site, 
                            min_adsorbate_distance):
        """Returns True if the site on the atoms object is occupied 
        by a specific species"""
        # if site['occupied']:
        #     return True
        if True not in atoms.get_pbc():
            ads_symbols = molecule(adsorbate).get_chemical_symbols()
            n_ads_atoms = len(ads_symbols)
            # play aruond with the cutoff
            height = site['height']
            normal = np.array(site['normal'])
            pos = np.array(site['adsorbate_position']) + normal * height
            dists = []
            for a in atoms:
                if a.symbol in set(ads_symbols):
                    dists.append((a.index, np.linalg.norm(pos - a.position)))
            for (i, d) in dists:
                if d < min_adsorbate_distance:
                    site_ads_symbols = []
                    if n_ads_atoms > 1:
                        for k in range(i,i+n_ads_atoms):
                            site_ads_symbols.append(atoms[k].symbol)
                    else:
                        site_ads_symbols.append(atoms[i].symbol)
                    if sorted(site_ads_symbols) == sorted(ads_symbols):               
                    # print('under min d', d, pos)
                    # site['occupied'] = 1
                        return True
            return False
        else:
            ads_symbols = molecule(adsorbate).get_chemical_symbols()
            n_ads_atoms = len(ads_symbols)
            cell = atoms.get_cell()
            pbc = np.array([cell[0][0], cell[1][1], 0])
            pos = np.array(site['adsorbate_position'])
            dists = []
            for a in atoms:
                if a.symbol in set(ads_symbols):
                    dists.append((a.index, get_mic_distance(pos, a.position, 
                                                            atoms)))
            for (i, d) in dists:
                if d < min_adsorbate_distance:
                    site_ads_symbols = []
                    if n_ads_atoms > 1:
                        for k in range(i,i+n_ads_atoms):
                            site_ads_symbols.append(atoms[k].symbol)
                    else:
                        site_ads_symbols.append(atoms[i].symbol)
                    if sorted(site_ads_symbols) == sorted(ads_symbols):               
                    # print('under min d', d, pos)
                    # site['occupied'] = 1
                        return True
            return False

    @classmethod
    def convert_adsorbate(cls, adsorbate):
        """Converts the adsorbate to an Atoms object"""
        if isinstance(adsorbate, Atoms):
            ads = adsorbate
        elif isinstance(adsorbate, Atom):
            ads = Atoms([adsorbate])
        else:
            # Hope it is a useful string or something like that
#            if adsorbate == 'CO':
#                # CO otherwise comes out as OC - very inconvenient
#                ads = molecule(adsorbate, symbols=adsorbate)
#            else:
#                ads = molecule(adsorbate)
            ads = molecule(adsorbate)
        ads.translate(-ads[0].position)
        return ads


class AddAdsorbate(AdsorbateOperator):
    """
    Use this operator to add adsorbates to the surface.
    The surface is allowed to change during the algorithm run.

    Site and surface preference can be supplied. If both are supplied site
    will be considered first.

    Supplying a tilt angle will tilt the adsorbate with an angle relative
    to the standard perpendicular to the surface
    """
    def __init__(self, adsorbate,
                 min_adsorbate_distance=2.,
                 site_preference=None,
                 surface_preference=None,
                 tilt_angle=None,
                 num_muts=1):
        AdsorbateOperator.__init__(self, adsorbate,
                                   num_muts=num_muts)
        self.descriptor = 'AddAdsorbate'

        self.min_adsorbate_distance = min_adsorbate_distance

        self.site_preference = site_preference
        self.surface_preference = surface_preference
        
        self.tilt_angle = tilt_angle or 0.

        self.min_inputs = 1

    def get_new_individual(self, parents):
        """Returns the new individual as an atoms object"""
        f = parents[0]

        indi = self.initialize_individual(f)
        indi.info['data']['parents'] = [f.info['confid']]

        for atom in f:
            indi.append(atom)

        ads_sites = enumerate_monometallic_sites(indi)
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

            added = self.add_adsorbate(indi, ads_sites,
                                       self.min_adsorbate_distance,
                                       tilt_angle=self.tilt_angle)
            if not added:
                break

        return (self.finalize_individual(indi),
                self.descriptor + ': {0}'.format(f.info['confid']))


class RemoveAdsorbate(AdsorbateOperator):
    """This operator removes an adsorbate from the surface. It works
    exactly (but doing the opposite) as the AddAdsorbate operator."""
    def __init__(self, adsorbate,
                 site_preference=None,
                 surface_preference=None,
                 num_muts=1):
        AdsorbateOperator.__init__(self, adsorbate,
                                   num_muts=num_muts)
        self.descriptor = 'RemoveAdsorbate'

        self.site_preference = site_preference
        self.surface_preference = surface_preference

        self.min_inputs = 1

    def get_new_individual(self, parents):
        f = parents[0]

        indi = self.initialize_individual(f)
        indi.info['data']['parents'] = [f.info['confid']]

        for atom in f:
            indi.append(atom)

        ads_sites = enumerate_monometallic_sites(indi)
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

            removed = self.remove_adsorbate(indi, ads_sites)

            if not removed:
                break

        return (self.finalize_individual(indi),
                self.descriptor + ': {0}'.format(f.info['confid']))


class MoveAdsorbate(AdsorbateOperator):
    """This operator removes an adsorbate from the surface and adds it
    again at a different position, i.e. effectively moving the adsorbate."""
    def __init__(self, adsorbate,
                 min_adsorbate_distance=2.,
                 site_preference_from=None,
                 surface_preference_from=None,
                 site_preference_to=None,
                 surface_preference_to=None,
                 num_muts=1):
        AdsorbateOperator.__init__(self, adsorbate,
                                   num_muts=num_muts)
        self.descriptor = 'MoveAdsorbate'

        self.min_adsorbate_distance = min_adsorbate_distance

        self.site_preference_from = site_preference_from
        self.surface_preference_from = surface_preference_from
        self.site_preference_to = site_preference_to
        self.surface_preference_to = surface_preference_to

        self.min_inputs = 1

    def get_new_individual(self, parents):
        f = parents[0]

        indi = self.initialize_individual(f)
        indi.info['data']['parents'] = [f.info['confid']]

        for atom in f:
            indi.append(atom)
         
        ads_sites = enumerate_monometallic_sites(indi)
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
                                            for_move=True)

            random.shuffle(ads_sites)
            if self.surface_preference_to is not None:
                def func(x):
                    return x['surface'] == self.surface_preference_to
                ads_sites.sort(key=func, reverse=True)

            if self.site_preference_to is not None:
                def func(x):
                    return x['site'] == self.site_preference_to
                ads_sites.sort(key=func, reverse=True)

            added = self.add_adsorbate(indi, ads_sites,
                                       self.min_adsorbate_distance)

            if (not removed) or (not added):
                break

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
    def __init__(self, adsorbate, blmin, keep_composition=True,
                 fix_coverage=False, min_adsorbate_distance=2.,
                 rotate_vectors=None, rotate_angles=None):

        AdsorbateOperator.__init__(self, adsorbate)
        self.blmin = blmin
        self.keep_composition = keep_composition
        self.fix_coverage = fix_coverage
        self.min_adsorbate_distance = min_adsorbate_distance
        self.rvecs = rotate_vectors
        self.rangs = rotate_angles
        self.descriptor = 'CutSpliceCrossoverWithAdsorbates'
        
        self.min_inputs = 2
        
    def get_new_individual(self, parents):
        f, m = parents
        
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
                print('rotation vectors are not a list, skipping rotation')
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
        e = np.array((np.sin(phi) * np.cos(theta),
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

        ads_sites = enumerate_monometallic_sites(indi)           
        if self.fix_coverage:
            # Remove or add adsorbates as needed
            adsorbates_in_child = self.get_all_adsorbate_indices(indi)
            diff = len(adsorbates_in_child) - adsorbates_in_parents
            if diff < 0:
                # Add adsorbates
                for _ in range(abs(diff)):
                    self.add_adsorbate(indi, ads_sites,
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
                if a.symbol in self.adsorbate_set]]
        return ac.numbers
        
    def get_atoms_without_adsorbates(self, atoms):
        ac = atoms.copy()
        del ac[[a.index for a in ac
                if a.symbol in self.adsorbate_set]]
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


def label_occupied_sites(atoms, adsorbate, second_shell=False):
    '''Assign labels to all occupied sites. Different labels represent 
    different sites.
    
    The label is defined as the number of atoms being labeled at that site 
    (considering second shell).
    
    Change the 2 metal elements to 2 pseudo elements for sites occupied by a 
    certain species. If multiple species are present, the 2 metal elements 
    are assigned to multiple pseudo elements. Atoms that are occupied by 
    multiple species also need to be changed to new pseudo elements. Currently 
    only a maximum of 2 species is supported.
    
    Note: Please provide atoms including adsorbate(s), with adsorbate being a 
    string or a list of strings.
    
    Set second_shell=True if you also want to label the second shell atoms.'''

    species_pseudo_mapping = [('As','Sb'),('Se','Te'),('Br','I')]  
    elements = list(set(atoms.symbols))
    metals = [element for element in elements if element not in adsorbates]
    mA = metals[0]
    mB = metals[1]
    if Atom(metals[0]).number > Atom(metals[1]).number:
        mA = metals[1]
        mB = metals[0]
    sites = enumerate_monometallic_sites(atoms, second_shell=second_shell)
    n_occupied_sites = 0
    atoms.set_tags(0)
    if isinstance(adsorbate, list):               
        if len(adsorbate) == 2:
            for site in sites:            
                for ads in adsorbate:
                    k = adsorbate.index(ads)
                    ao = AdsorbateOperator(ads, sites)
                    if ao.is_site_occupied_by(atoms, ads, site, 
                                              min_adsorbate_distance=0.2):
                        site['occupied'] = 1
                        site['adsorbate'] = ads
                        indices = site['indices']
                        label = site['label']
                        for idx in indices:                
                            if atoms[idx].tag == 0:
                                atoms[idx].tag = label
                            else:
                                atoms[idx].tag = str(atoms[idx].tag) + label
                            if atoms[idx].symbol not in \
                            species_pseudo_mapping[0]+species_pseudo_mapping[1]:
                                if atoms[idx].symbol == mA:
                                    atoms[idx].symbol = \
                                    species_pseudo_mapping[k][0]
                                elif atoms[idx].symbol == mB:
                                    atoms[idx].symbol = \
                                    species_pseudo_mapping[k][1]
                            else:
                                if atoms[idx].symbol == \
                                   species_pseudo_mapping[k-1][0]:
                                    atoms[idx].symbol = \
                                    species_pseudo_mapping[2][0]
                                elif atoms[idx].symbol == \
                                     species_pseudo_mapping[k-1][1]:\
                                    atoms[idx].symbol = \
                                    species_pseudo_mapping[2][1]
                        n_occupied_sites += 1 
        else:
            raise NotImplementedError
    else:
        ao = AdsorbateOperator(adsorbate, sites)
        for site in sites:
            if ao.is_site_occupied(atoms, site, min_adsorbate_distance=0.2):
                site['occupied'] = 1
                indices = site['indices']
                label = site['label']
                for idx in indices:                
                    if atoms[idx].tag == 0:
                        atoms[idx].tag = label
                    else:
                        atoms[idx].tag = str(atoms[idx].tag) + label
                    # Map to pseudo elements even when there is only one 
                    # adsorbate species (unnecessary)
                    #if atoms[idx].symbol == mA:
                    #    atoms[idx].symbol = species_pseudo_mapping[0][0]
                    #elif atoms[idx].symbol == mB:
                    #    atoms[idx].symbol = species_pseudo_mapping[0][1]
                n_occupied_sites += 1
    tag_set = set([a.tag for a in atoms])
    print('{0} sites labeled with tags including {1}'.format(n_occupied_sites, 
                                                             tag_set))

    return atoms


def multi_label_counter(atoms, adsorbate, second_shell=False):
    '''Encoding the labels into 5d numpy arrays. 
    This can be further used as a fingerprint.

    Atoms that constitute an occupied adsorption site will be labeled as 1.
    If an atom contributes to multiple sites of same type, the number wil 
    increase. One atom can encompass multiple non-zero values if it 
    contributes to multiple types of sites.

    Note: Please provide atoms including adsorbate(s), with adsorbate being a 
    string or a list of strings.

    Set second_shell=True if you also want to label the second shell atoms.'''

    labeled_atoms = label_occupied_sites(atoms, adsorbate, second_shell)
    np_indices = [a.index for a in labeled_atoms if a.symbol not in adsorbates]
    np_atoms = labeled_atoms[np_indices]
    
    counter_lst = []
    for atom in np_atoms:
        if atom.symbol not in adsorbates:
            if atom.tag == 0:
                counter_lst.append(np.zeros(5).astype(int).tolist())
            else:
                line = str(atom.tag)
                cns = [int(s) for s in line]
                lst = np.zeros(5).astype(int).tolist()
                for idx in cns:
                    lst[idx-1] += int(1)
                counter_lst.append(lst)

    return counter_lst
