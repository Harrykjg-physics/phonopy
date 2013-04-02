# Copyright (C) 2011 Atsushi Togo
# All rights reserved.
#
# This file is part of phonopy.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# * Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in
#   the documentation and/or other materials provided with the
#   distribution.
#
# * Neither the name of the phonopy project nor the names of its
#   contributors may be used to endorse or promote products derived
#   from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import numpy as np
import StringIO
from phonopy.structure.atoms import Atoms, symbol_map, atom_data
from phonopy.structure.cells import Primitive
from phonopy.structure.symmetry import Symmetry
from phonopy.harmonic.force_constants import similarity_transformation

class VasprunWrapper(object):
    """VasprunWrapper class
    This is used to avoid VASP 5.2.8 vasprun.xml defect at PRECFOCK,
    xml parser stops with error.
    """
    def __init__(self, filename):
        self.f = open(filename)

    def read(self, size=None):
        element = self.f.next()
        if element.find("PRECFOCK") == -1:
            return element
        else:
            return "<i type=\"string\" name=\"PRECFOCK\"></i>"

def write_supercells_with_displacements(supercell,
                                        cells_with_displacements):
    write_vasp("SPOSCAR", supercell, direct=True)
    for i, cell in enumerate(cells_with_displacements):
        write_vasp('POSCAR-%03d' % (i+1), cell, direct=True)

    write_magnetic_moments(supercell)


def write_magnetic_moments(cell):
    magmoms = cell.get_magnetic_moments() 
    if not magmoms == None:
        w = open("MAGMOM", 'w')
        num_atoms, symbols, scaled_positions, sort_list = \
            sort_positions_by_symbols(cell.get_chemical_symbols(),
                                      cell.get_scaled_positions())
        w.write(" MAGMOM = ")
        for i in sort_list:
            w.write("%f " % magmoms[i])
        w.write("\n")
        w.close()
                

def get_forces_vasprun_xml(vasprun):
    """
    vasprun = etree.iterparse(filename, tag='varray')
    """
    forces = []
    num_atom = 0
    for event, element in vasprun:
        if element.attrib['name'] == 'forces':
            for v in element.xpath('./v'):
                forces.append([float(x) for x in v.text.split()])
                
    return np.array(forces)

def get_force_constants_vasprun_xml(vasprun):
    fc_tmp = None
    num_atom = 0
    for event, element in vasprun:
        if num_atom==0:
            atom_types, masses, num_atom = get_atom_types_from_vasprun_xml(element)

        # Get Hessian matrix (normalized by masses)
        if element.tag == 'varray':
            if element.attrib['name'] == 'hessian':
                fc_tmp = []
                for v in element.xpath('./v'):
                    fc_tmp.append([float(x) for x in v.text.strip().split()])

    if fc_tmp==None:
        return False
    else:
        fc_tmp = np.array(fc_tmp)
        if not fc_tmp.shape==(num_atom*3, num_atom*3):
            return False
        # num_atom = fc_tmp.shape[0] / 3
        force_constants = np.zeros((num_atom, num_atom, 3, 3), dtype=float)
    
        for i in range(num_atom):
            for j in range(num_atom):
                force_constants[i, j] = fc_tmp[i*3:(i+1)*3, j*3:(j+1)*3]
    
        # Inverse normalization by atomic weights
        for i in range(num_atom):
            for j in range(num_atom):
                force_constants[i, j] *= -np.sqrt(masses[i] * masses[j])
    
        return force_constants, atom_types

def get_atom_types_from_vasprun_xml(element):
    atom_types = []
    masses = []
    num_atom = 0
    
    if element.tag == 'array':
        if 'name' in element.attrib:
            if element.attrib['name'] == 'atomtypes':
                for rc in element.xpath('./set/rc'):
                    atom_info = [x.text for x in rc.xpath('./c')]
                    num_atom += int(atom_info[0])
                    atom_types.append(atom_info[1].strip())
                    masses += ([float(atom_info[2])] * int(atom_info[0]))

    return atom_types, masses, num_atom

def get_force_constants_OUTCAR(filename):
    file = open(filename)
    while 1:
        line = file.readline()
        if line == '':
            print "Force constants could not be found."
            return 0

        if line[:19] == " SECOND DERIVATIVES":
            break

    file.readline()
    num_atom = int(((file.readline().split())[-1].strip())[:-1])

    fc_tmp = []
    for i in range(num_atom * 3):
        fc_tmp.append([float(x) for x in (file.readline().split())[1:]])

    fc_tmp = np.array(fc_tmp)

    force_constants = np.zeros((num_atom, num_atom, 3, 3), dtype=float)
    for i in range(num_atom):
        for j in range(num_atom):
            force_constants[i, j] = -fc_tmp[i*3:(i+1)*3, j*3:(j+1)*3]

    return force_constants
    
def get_born_OUTCAR(poscar_filename="POSCAR",
                    outcar_filename="OUTCAR",
                    primitive_axis=np.eye(3),
                    is_symmetry=True,
                    symmetrize_tensors=False):
    cell = read_vasp(poscar_filename)
    primitive = Primitive(cell, primitive_axis)
    p2p = primitive.get_primitive_to_primitive_map()
    symmetry = Symmetry(primitive, is_symmetry=is_symmetry)
    independent_atoms = symmetry.get_independent_atoms()
    prim_lat = primitive.get_cell().T
    outcar = open(outcar_filename)
    
    borns = []
    while True:
        line = outcar.readline()
        if not line:
            break
    
        if "NIONS" in line:
            num_atom = int(line.split()[11])
    
        if "MACROSCOPIC STATIC DIELECTRIC TENSOR" in line:
            epsilon = []
            outcar.readline()
            epsilon.append([float(x) for x in outcar.readline().split()])
            epsilon.append([float(x) for x in outcar.readline().split()])
            epsilon.append([float(x) for x in outcar.readline().split()])
    
        if "BORN" in line:
            outcar.readline()
            line = outcar.readline()
            if "ion" in line:
                for i in range(num_atom):
                    born = []
                    born.append([float(x) for x in outcar.readline().split()][1:])
                    born.append([float(x) for x in outcar.readline().split()][1:])
                    born.append([float(x) for x in outcar.readline().split()][1:])
                    outcar.readline()
                    borns.append(born)


    reduced_borns = []
    for p_i, u_i in enumerate(p2p):
        if p_i in independent_atoms:
            if symmetrize_tensors:
                site_sym = [similarity_transformation(prim_lat, rot)
                            for rot in symmetry.get_site_symmetry(p_i)]
                reduced_borns.append(symmetrize_tensor(borns[u_i], site_sym))
            else:
                reduced_borns.append(borns[u_i])
                
    if symmetrize_tensors:
        point_sym = [similarity_transformation(prim_lat, rot)
                     for rot in symmetry.get_pointgroup_operations()]
        epsilon = symmetrize_tensor(epsilon, point_sym)
    else:
        epsilon = np.array(epsilon)

    return np.array(reduced_borns), epsilon
    
def symmetrize_tensor(tensor, symmetry_operations):
    tensors = np.zeros_like(tensor)
    for sym in symmetry_operations:
        tensors += similarity_transformation(sym, tensor)
    return tensors / len(symmetry_operations)

#
# read VASP POSCAR
#
def expand_symbols(num_atoms, symbols=None):
    expanded_symbols = []
    is_symbols = True
    if symbols == None:
        is_symbols = False
    else:
        if not len(symbols) == len(num_atoms):
            is_symbols = False
        else:
            for s in symbols:
                if not s in symbol_map:
                    is_symbols = False
                    break
    
    if is_symbols:
        for s, num in zip(symbols, num_atoms):
            expanded_symbols += [s] * num
    else:
        for i, num in enumerate(num_atoms):
            expanded_symbols += [atom_data[i+1][1]] * num

    return expanded_symbols

def is_exist_symbols(symbols):
    for s in symbols:
        if not (s in symbol_map):
            return False
    return True

def read_vasp(filename, symbols=None):
    f = open(filename)
    return get_atoms_from_poscar(f, symbols)

def read_vasp_from_strings(strings, symbols=None):
    return get_atoms_from_poscar(StringIO.StringIO(strings), symbols)

def get_atoms_from_poscar(f, symbols):
    lines = f.readlines()

    line1 = [x for x in lines[0].split()]
    if is_exist_symbols(line1):
        symbols = line1

    scale = float(lines[1])

    cell = []
    for i in range(2, 5):
        cell.append([float(x) for x in lines[i].split()[:3]])
    cell = np.array(cell) * scale

    try:
        num_atoms = np.array([int(x) for x in lines[5].split()])
        line_at = 6
    except ValueError:
        symbols = [x for x in lines[5].split()]
        num_atoms = np.array([int(x) for x in lines[6].split()])
        line_at = 7
    
    expaned_symbols = expand_symbols(num_atoms, symbols)

    if lines[line_at][0].lower() == 's':
        line_at += 1

    is_scaled = True
    if (lines[line_at][0].lower() == 'c' or
        lines[line_at][0].lower() == 'k'):
        is_scaled = False

    line_at += 1

    positions = []
    for i in range(line_at, line_at + num_atoms.sum()):
        positions.append([float(x) for x in lines[i].split()[:3]])

    if is_scaled:
        atoms = Atoms(symbols=expaned_symbols,
                      cell=cell,
                      scaled_positions=positions)
    else:
        atoms = Atoms(symbols=expaned_symbols,
                      cell=cell,
                      positions=positions)
        
    return atoms
                   
#
# write vasp POSCAR
#
def get_reduced_symbols(symbols):
    reduced_symbols = []
    for s in symbols:
        if not (s in reduced_symbols):
            reduced_symbols.append(s)
    return reduced_symbols

def sort_positions_by_symbols(symbols, positions):
    reduced_symbols = get_reduced_symbols(symbols)
    sorted_positions = []
    sort_list = []
    num_atoms = np.zeros(len(reduced_symbols), dtype=int)
    for i, rs in enumerate(reduced_symbols):
        for j, (s, p) in enumerate(zip(symbols, positions)):
            if rs==s:
                sorted_positions.append(p)
                sort_list.append(j)
                num_atoms[i] += 1
    return num_atoms, reduced_symbols, np.array(sorted_positions), sort_list

def write_vasp(filename, atoms, direct=True):

    num_atoms, symbols, scaled_positions, sort_list = \
        sort_positions_by_symbols(atoms.get_chemical_symbols(),
                                  atoms.get_scaled_positions())
    lines = ""     
    for s in symbols:
        lines += "%s " % s
    lines += "\n"
    lines += "   1.0\n"
    for a in atoms.get_cell():
        lines += " %22.16f%22.16f%22.16f\n" % tuple(a)
    lines += ("%4d" * len(num_atoms)) % tuple(num_atoms)
    lines += "\n"
    lines += "Direct\n"
    for vec in scaled_positions:
        for x in (vec - vec.round()):
            if float('%20.16f' % x) < 0.0:
                lines += "%20.16f" % (x + 1.0)
            else:
                lines += "%20.16f" % (x)
        lines += "\n"

    f = open(filename, 'w')
    f.write(lines)

if __name__ == '__main__':
    import sys
    atoms = read_vasp(sys.argv[1])
    write_vasp('%s-new' % sys.argv[1], atoms)
