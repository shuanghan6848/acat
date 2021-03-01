# ACAT: **A**lloy **C**atalysis **A**utomated **T**oolkit
ACAT is a Python package for atomistic modelling of metal / alloy catalysts used in heterogeneous catalysis. The package is based on automatic identifications of adsorption sites and adsorbate coverages on surface slabs and nanoparticles. Synergized with ASE, ACAT provides useful tools for building atomistic models of alloy catalysts with and without adsorbates. The goal is to automate workflows so that the structure generations can be readily adapted in a global optimization.

ACAT has been developed by Shuang Han at the Section of Atomic Scale Materials Modelling, Department of Energy Conversion and Storage, Technical University of Denmark (DTU) in Lyngby, Denmark.

To use ACAT, please see `ACAT documentation <https://shuanghan.gitlab.io/acat>`_.

![](images/color_facets.png)

## Developers: 
Shuang Han (shuha@dtu.dk) - current maintainer

## Dependencies
* python>=3.6
* networkx>=2.4
* ase
* asap3

## Installation
Clone the repository:

```git clone https://gitlab.com/shuanghan/acat.git```

Go to the installed path and install all dependencies:

```pip install -r requirements.txt --user```

Install the main package:

```python setup.py install --user```
 
## Known issues
1. Some functions distinguishes between nanoparticle and surface slabs based on periodic boundary condition (PBC). Therefore, before using the code, it is recommended to **set all directions as non-periodic for nanoparticles and at least one direction periodic for surface slabs, and also add vacuum layers to all non-periodic directions. Note that the half-top half-bottom slab model is not supported by the code. Please make sure the slab is a unity.**
2. ACAT uses a regularized adsorbate string representation. In each adsorbate string, **the first element must set to the bonded atom. If the adsorbate is multi-dentate, the order follows the order of their atomic numbers. Hydrogen should always follow the element that it bonds to.** For example, water should be written as 'OH2', hydrogen peroxide should be written as 'OHOH', ethanol should be written as 'CH3CH2OH', formyl should be written as 'CHO', hydroxymethylidyne should be written as 'COH'. If the string is not supported by the code, it will return the ase.build.molecule instead, which could result in a weird orientation. If the string is not supported by this code nor ASE, you can make your own molecules in the adsorbate_molecule function in acat.settings.
3. There is a bug that causes ``get_neighbor_site_list()`` to not return the correct neighbor site indices with ASE version <= 3.18. This is most likely due to shuffling of indices in some ASE functions, which is solved after the release of ASE 3.19.0. 
