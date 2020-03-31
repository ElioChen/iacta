import os
import shutil
import subprocess
import numpy as np
import tempfile
import re

def successive_optimization(xtb,
                            initial_xyz,
                            constraints,
                            parameters,
                            verbose=True):
    """Optimize a structure through successive constraints.

    Takes an initial structure and successively optimize it applying the
    sequence of $constrain objects in constraints. These can be generated by
    code such as this one, which stretch a bond between atoms 10 and 11 in
    initial_xyz from 1.06 A to 3 x 1.06 A in 80 steps,

    stretch_factors = np.linspace(1.0, 3.0, 80)
    constraints = [("force constant = 0.5",
                    "distance: %i, %i, %f" % (10, 11, stretch * 1.06)
                   for stretch in stretch_factors]

    Parameters:
    -----------

    xtb (xtb_driver) : driver object for xtb.

    initial_xyz (str): path to initial structure xyz file.

    constraints (list): list of constraints. Each constraints should be a
    tuple of parameters to be put into a $constrain group in xcontrol.

    parameters (dict) : additional parameters, as obtained from
    default_parameters() above. TODO: Describe parameters in more details

    Optional Parameters:
    --------------------

    verbose (bool) : print information about the run. defaults to True.

    Returns:
    --------

    structures : list of .xyz formatted strings that include every structure
    through the multiple optimization.

    energies : list of floats of xtb energies (in Hartrees) for the structures.

    opt_indices : list of integers representing the indices of the optimized
    structures at each step.

    """
    if not constraints:
        # nothing to do
        return [], [], []

    # Make scratch files
    fdc, current = tempfile.mkstemp(suffix=".xyz", dir=xtb.scratchdir)
    fdl, log = tempfile.mkstemp(suffix="_log.xyz", dir=xtb.scratchdir)

    # prepare the current file
    shutil.copyfile(initial_xyz, current)
    structures = []
    energies = []
    opt_indices = []
    

    if verbose:
        print("  %i successive optimizations" % len(constraints))

    for i in range(len(constraints)):
        direction = "->"
        if verbose:
            print("      " + direction + "  %3i " % i, end="")
            
        opt = xtb.optimize(current,
                           current,
                           log=log,
                           level=parameters["optlevel"],
                           xcontrol=dict(
                               wall=parameters["wall"],
                               constrain=constraints[i]))
        opt()
        
        news, newe = read_trajectory(log)
        structures += news
        energies += newe
        opt_indices += [len(structures)-1]
        if verbose:
            print("   nsteps=%4i   Energy=%9.5f Eh"%(len(news), newe[-1]))

    os.remove(current)
    os.remove(log)
    return structures, energies, opt_indices
        

def metadynamics_job(xtb,
                     mtd_index,
                     input_folder,
                     output_folder,
                     constraints,
                     parameters):
    """Return a metadynamics search job for other "transition" conformers.

    mtd_index is the index of the starting structure to use as a starting
    point in the metadynamics run. Returns an unevaluated xtb_job to be used
    in ThreadPool.

    Parameters:
    -----------

    xtb (xtb_driver) : driver object for xtb.

    mtd_index (int) : index of the starting structure, as generated from
    generate_starting_structures. Correspond to the index of the element in
    the constratins list for which metadynamics is run.

    input_folder (str) : folder containing the MTD input structures.

    output_folder (str) : folder where results are stored.

    constraints (list): list of constraints. Each constraints should be a
    tuple of parameters to be put into a $constrain group in xcontrol.

    parameters (dict) : additional parameters, as obtained from
    default_parameters() above. TODO: Describe parameters in more details

    Optional Parameters:
    --------------------

    verbose (bool) : print information about the run. defaults to True.

    Returns:
    --------

    None

    """
    os.makedirs(output_folder, exist_ok=True)
    
    mjob = xtb.metadyn(input_folder + "/opt%4.4i.xyz" % mtd_index,
                       output_folder + "/mtd%4.4i.xyz" % mtd_index,
                       xcontrol=dict(
                           wall=parameters["wall"],
                           metadyn=parameters["metadyn"],
                           md=parameters["md"],
                           constrain=constraints[mtd_index]))
    return mjob

    
    
    


def reaction_job(xtb,
                 initial_xyz,
                 mtd_index,
                 output_folder,
                 constraints,
                 parameters):
    """Take structures generated by metadynamics and build a reaction trajectory.

    Takes a structure generated by metadynamics_search() and successively
    optimize it by applying the sequence of $constrain objects in constraints
    forward from mtd_index to obtain products, and backward from mtd_index to
    obtain reactants.

    This is the final step in the reaction space search, and it generates
    molecular trajectories. It should be noted that this function returns an
    unevaluated job, to be fed to ThreadPool.

    Parameters:
    -----------

    xtb (xtb_driver) : driver object for xtb.

    initial_xyz (str) : initial xyz as a string.

    mtd_index (int) : Index of the element in the constraints list that
    generated the starting structures.

    output_folder (str) : folder where results are stored.

    constraints (list): list of constraints. Each constraints should be a
    tuple of parameters to be put into a $constrain group in xcontrol.

    parameters (dict) : additional parameters, as obtained from
    default_parameters() above. TODO: Describe parameters in more details

    Optional Parameters:
    --------------------

    verbose (bool) : print information about the run. defaults to True.

    Returns:
    --------

    react_job() : function which, when evaluated, computes the trajectory

    """

    def react_job():
        os.makedirs(output_folder, exist_ok=True)

        f = open(output_folder + "/initial.xyz", "w")
        f.write(initial_xyz)
        f.close()

        # Forward reaction
        fstructs, fe, fopt = successive_optimization(
            xtb, output_folder + "/initial.xyz",
            # None -> no constraint = products
            constraints[mtd_index:] + [None],
            parameters,
            verbose=False)          # otherwise its way too verbose

        f = open(output_folder + "/initial_backward.xyz", "w")
        f.write(fstructs[0])
        f.close()

        # Backward reaction
        bstructs, be, bopt = successive_optimization(
            xtb, output_folder + "/initial_backward.xyz",
            # None -> no constraint = reactants  
            constraints[mtd_index-1:-1:-1] + [None],
            parameters,
            verbose=False)          # otherwise its way too verbose


        # Dump forward reaction and backward reaction quantities
        dump_succ_opt(output_folder,
                      bstructs[::-1] + fstructs,
                      be[::-1] + fe,
                      bopt[::-1] + fopt,
                      concat=True,
                      extra=True)
        
    return react_job
                  


def read_trajectory(filepath):
    """Read an xyz file containing a trajectory."""
    structures = []
    energies = []
    with open(filepath, 'r') as f:
        while True:
            first_line = f.readline()
            # EOF -> blank line
            if not first_line:
                break
                
            this_mol = first_line
            natoms = int(first_line.rstrip())

            comment_line = f.readline()
            this_mol += comment_line
            # first number on comment_line
            m = re.search('-?[0-9]*\.[0-9]*', comment_line)       
            energies += [float(m.group())]
        
            for i in range(natoms):
                this_mol += f.readline()

            structures += [this_mol]
    return structures,energies

def dump_succ_opt(output_folder, structures, energies, opt_indices,
                  concat=False,
                  extra=True):
    os.makedirs(output_folder, exist_ok=True)
    

    if concat:
        # Dump the optimized structures in one file                
        with open(output_folder + "/opt.xyz", "w") as f:
            for oi in opt_indices:
                f.write(structures[oi])
    else:
        # Dump the optimized structures in many files            
        for stepi, oi in enumerate(opt_indices):
            with open(output_folder + "/opt%4.4i.xyz" % stepi, "w") as f:
                f.write(structures[oi])

    # Dump indices of optimized structures, energies of optimized structures,
    # all energies and all structures
    np.savetxt(output_folder + "/Eopt", np.array(energies)[opt_indices], fmt="%15.8f")

    if extra:
        np.savetxt(output_folder + "/indices", opt_indices, fmt="%i")
        np.savetxt(output_folder + "/E", energies, fmt="%15.8f")
        with open(output_folder + "/log.xyz", "w") as f:
            for s in structures:
                f.write(s)





