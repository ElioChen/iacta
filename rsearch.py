import numpy as np
import react
import xtb_utils
import os
import shutil
import argparse

parser = argparse.ArgumentParser(
    description="Driver for reaction search.",
    )
parser.add_argument("init_xyz",
                    help="Path to file containing the starting geometry.",
                    type=str)
parser.add_argument("atoms",
                    help="Atoms that define the bond to be stretched, numbered according"
                    +" to init_xyz. (NOTE THIS IS 1-INDEXED)",
                    type=int, nargs=2)
parser.add_argument("-o",
                    help="Output folder. defaults to \"output\"",
                    type=str, default="output")
parser.add_argument("-T",
                    help="Number of threads to use.",
                    type=int, default=1)
parser.add_argument("-s",
                    help="Bond stretch limits. Defaults to (1.0, 3.0)",
                    nargs=2,type=float, default=[1.0,3.0])
parser.add_argument("-sn",
                    help="Number of bond stretches. Defaults to 30.",
                    type=int, default=30)
parser.add_argument("-mtdi",
                    help="Indices of the stretches where MTD is done.",
                    type=int, nargs="+", default=[0, 5, 10])
parser.add_argument("--force",
                    help="Force constant of the stretch, defaults to 1.25", default=1.25,
                    type=int)
parser.add_argument("--no-opt",
                    help="Start with an xtb optimization (defaults to true).",
                    action="store_true")
parser.add_argument("--gfn",
                    help="gfn version. Defaults to GFN 2", default="2",
                    type=str)
parser.add_argument("--etemp",
                    help="Electronic temperature. Defaults to 300 K", default="300.0",
                    type=str)


args = parser.parse_args()
out_dir = args.o
os.makedirs(out_dir)
# copy the initial file over
init = shutil.copy(args.init_xyz, out_dir)

# Initialize the xtb driver
xtb = xtb_utils.xtb_driver()
xtb.extra_args = ["--gfn " + args.gfn, "--etemp " + args.etemp]

if not args.no_opt:
    xtb.optimize(init, init, level="vtight")


# Get additional molecular parameters
atoms, positions = xtb_utils.read_xyz(init)
N = len(atoms)
bond_length0 = positions[args.atoms[0]-1] - positions[args.atoms[1]-1]
bond_length0 = np.sqrt(bond_length0.dot(bond_length0))
bond = (args.atoms[0], args.atoms[1], bond_length0)
params = react.default_parameters(N)

# Constraints for the search
# -------------------------
stretch_factors = np.linspace(args.s[0], args.s[1], args.sn)
constraints = [("force constant = %f" % args.force,
                "distance: %i, %i, %f"% (bond[0],bond[1],
                                         stretch * bond[2]))
               for stretch in stretch_factors]
mtd_indices = args.mtdi


# STEP 1: Initial generation of guesses
# ----------------------------------------------------------------------------
react.generate_initial_structures(
    xtb, out_dir,
    init,
    constraints,
    params)

# STEP 2: Metadynamics
# ----------------------------------------------------------------------------
react.metadynamics_search(
    xtb, out_dir,
    mtd_indices,
    constraints,
    params,
    nthreads=args.T)

# STEP 2: Reactions
# ----------------------------------------------------------------------------
react.react(
    xtb, out_dir,
    mtd_indices,
    constraints,
    params,
    nthreads=args.T)