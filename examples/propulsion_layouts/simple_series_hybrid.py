
from openconcept.components.motor import SimpleMotor
from openconcept.components.splitter import PowerSplit
from openconcept.components.generator import SimpleGenerator
from openconcept.components.turboshaft import SimpleTurboshaft
from openconcept.components.battery import SimpleBattery
from openconcept.components.propeller import SimplePropeller
from openconcept.analysis.atmospherics.compute_atmos_props import ComputeAtmosphericProperties
from openconcept.utilities.dvlabel import DVLabel
from openconcept.utilities.math import AddSubtractComp


from openmdao.api import Problem, Group, IndepVarComp, BalanceComp, DirectSolver, NewtonSolver, ScipyKrylov
import matplotlib.pyplot as plt

import numpy as np

from openmdao.api import ExplicitComponent



class SeriesHybridElectricPropulsionSystem(Group):
    """This is an example model of a series-hybrid propulsion system. One motor
        draws electrical load from two sources in a fractional split| a battery pack,
        and a turbogenerator setup. The control inputs are the power split fraction and the
        motor throttle setting; the turboshaft throttle matches the power level necessary
        to drive the generator at the required power level.

        Fuel flows and prop thrust should be fairly accurate.

        Heat constraints have not yet been incorporated.
    """
    def initialize(self):
        self.options.declare('num_nodes',default=1,desc="Number of mission analysis points to run")


    def setup(self):
        #define design variables that are independent of flight condition or control states
        dvlist = [['ac|propulsion|engine|rating','eng1_rating',260.0,'kW'],
                    ['dv_prop1_diameter','prop1_diameter',2.5,'m'],
                    ['dv_motor1_rating','motor1_rating',240.0,'kW'],
                    ['dv_gen1_rating','gen1_rating',250.0,'kW'],
                    ['dv_batt1_weight','batt1_weight',2000,'kg']]
        self.add_subsystem('dvs',DVLabel(dvlist),promotes_inputs=["*"],promotes_outputs=["*"])
        nn = self.options['num_nodes']
        #introduce model components
        self.add_subsystem('motor1', SimpleMotor(efficiency=0.97,num_nodes=nn),promotes_inputs=["throttle"])
        self.add_subsystem('hybrid_split',PowerSplit(rule='fraction',num_nodes=nn))
        self.add_subsystem('gen1',SimpleGenerator(efficiency=0.97,num_nodes=nn))
        self.add_subsystem('eng1',SimpleTurboshaft(num_nodes=nn),promotes_outputs=["fuel_flow"])
        self.add_subsystem('batt1',SimpleBattery(num_nodes=nn))
        self.add_subsystem('prop1',SimplePropeller(num_nodes=nn),promotes_inputs=["fltcond_*"],promotes_outputs=["thrust"])

        #connect design variables to model component inputs
        self.connect('eng1_rating','eng1.shaft_power_rating')
        self.connect('prop1_diameter','prop1.diameter')
        self.connect('motor1_rating','motor1.elec_power_rating')
        self.connect('motor1_rating','prop1.power_rating')
        self.connect('gen1_rating','gen1.elec_power_rating')
        self.connect('batt1_weight','batt1.battery_weight')

        #connect components to each other
        self.connect('motor1.shaft_power_out','prop1.shaft_power_in')
        self.connect('eng1.shaft_power_out','gen1.shaft_power_in')
        self.connect('motor1.elec_load','hybrid_split.power_in')
        self.connect('hybrid_split.power_out_A','batt1.elec_load')

        # hack = self.add_subsystem('eng1throttlehack',IndepVarComp())
        # hack.add_output('throttle',np.ones(nn))

        # self.connect('eng1throttlehack.throttle','eng1.throttle')

        #there is an implicit gap between gen1 output and split input B
        #add implicit component to match gen1 elec output and hybrid_split.power_out_B
        # eng1_bal = BalanceComp()
        # eng1_bal.add_balance('eng1t', val=np.ones(nn)*0.5,eq_units='W')
        # self.add_subsystem('eng1_control',eng1_bal)
        # self.connect('eng1_control.eng1t','eng1.throttle')
        # self.connect('hybrid_split.power_out_B','eng1_control.lhs:eng1t')
        # self.connect('gen1.elec_power_out','eng1_control.rhs:eng1t')

        #self.linear_solver = ScipyKrylov()
        #self.nonlinear_solver = NewtonSolver()
        #self.nonlinear_solver.options['maxiter'] = 10


class SingleSeriesHybridElectricPropulsionSystem(Group):
    """This is an example model of a series-hybrid propulsion system. One motor
        draws electrical load from two sources in a fractional split| a battery pack,
        and a turbogenerator setup. The control inputs are the power split fraction and the
        motor throttle setting; the turboshaft throttle matches the power level necessary
        to drive the generator at the required power level.

        Fuel flows and prop thrust should be fairly accurate.
        Heat constraints haven't yet been incorporated.

        The "pilot" controls thrust by varying the motor throttles from 0 to 100+% of rated power.
        She may also vary the percentage of battery versus fuel being
        used by varying the power_split_fraction.

        This module alone cannot produce accurate fuel flows, battery loads, etc.
        You must do the following, either with an implicit solver or with the optimizer:
        - Set eng1.throttle such that gen1.elec_power_out = hybrid_split.power_out_A

        The battery does not track its own state of charge (SOC);
        it is connected to elec_load simply so that the discharge rate can be compared to
        the discharge rate capability of the battery. SOC and fuel flows should be time-integrated
        at a higher level (in the mission analysis codes).

        Inputs
        ------
        ac|propulsion|engine|rating : float
            Turboshaft range extender power rating (scalar, kW)
        ac|propulsion|propeller|diameter : float
            Propeller diameter (scalar, m)
        ac|propulsion|motor|rating : float
            Motor power rating (scalar, kW)
        ac|propulsion|generator|rating : float
            Range extender elec gen rating (scalar, kW)
        ac|weights|W_battery : float
            Battery weight (scalar, kg)

        TODO list all the control inputs

        Outputs
        -------
        thrust : float
            Propulsion system total thrust (vector, N)
        fuel_flow : float
            Fuel flow consumed by the turboshaft (vector, kg/s)

        Options
        -------
        num_nodes : float
            Number of analysis points to run (default 1)
        specific_energy : float
            Battery specific energy (default 300 Wh/kg)
    """
    def initialize(self):
        self.options.declare('num_nodes', default=1, desc="Number of mission analysis points to run")
        self.options.declare('specific_energy', default=300, desc="Battery spec energy in Wh/kg")

    def setup(self):
        nn = self.options['num_nodes']
        e_b = self.options['specific_energy']

        # define design variables that are independent of flight condition or control states
        dvlist = [['ac|propulsion|engine|rating', 'eng_rating', 260.0, 'kW'],
                    ['ac|propulsion|propeller|diameter', 'prop_diameter', 2.5, 'm'],
                    ['ac|propulsion|motor|rating', 'motor_rating', 240.0, 'kW'],
                    ['ac|propulsion|generator|rating', 'gen_rating', 250.0, 'kW'],
                    ['ac|weights|W_battery', 'batt_weight', 2000, 'kg']]
        self.add_subsystem('dvs', DVLabel(dvlist), promotes_inputs=["*"], promotes_outputs=["*"])

        # introduce model components
        self.add_subsystem('motor1', SimpleMotor(efficiency=0.97, num_nodes=nn))
        self.add_subsystem('prop1', SimplePropeller(num_nodes=nn),
                           promotes_inputs=["fltcond|*"], promotes_outputs=['thrust'])
        self.connect('motor1.shaft_power_out', 'prop1.shaft_power_in')

        self.add_subsystem('hybrid_split', PowerSplit(rule='fraction', num_nodes=nn))
        self.connect('motor1.elec_load', 'hybrid_split.power_in')

        self.add_subsystem('eng1',
                           SimpleTurboshaft(num_nodes=nn,
                                            weight_inc=0.14 / 1000,
                                            weight_base=104),
                           promotes_outputs=["fuel_flow"])
        self.add_subsystem('gen1',SimpleGenerator(efficiency=0.97, num_nodes=nn))

        self.connect('eng1.shaft_power_out', 'gen1.shaft_power_in')

        self.add_subsystem('batt1', SimpleBattery(num_nodes=nn, specific_energy=e_b))
        self.connect('hybrid_split.power_out_A', 'batt1.elec_load')

        # need to use the optimizer to drive hybrid_split.power_out_B to the
        # same value as gen1.elec_power_out.
        # create a residual equation for power in vs power out from the generator
        self.add_subsystem('eng_gen_resid',
                           AddSubtractComp(output_name='eng_gen_residual',
                                           input_names=['gen_power_available', 'gen_power_required'],
                                           vec_size=nn, units='kW',
                                           scaling_factors=[1, -1]))
        self.connect('hybrid_split.power_out_B', 'eng_gen_resid.gen_power_required')
        self.connect('gen1.elec_power_out', 'eng_gen_resid.gen_power_available')

        # add the weights of all the motors and props
        # (forward-compatibility for twin series hybrid layout)
        addweights = AddSubtractComp(output_name='motors_weight',
                                     input_names=['motor1_weight'],
                                     units='kg')
        addweights.add_equation(output_name='propellers_weight',
                                input_names=['prop1_weight'],
                                units='kg')
        self.add_subsystem('add_weights', subsys=addweights,
                           promotes_inputs=['*'],promotes_outputs=['*'])

        self.connect('motor1.component_weight', 'motor1_weight')
        self.connect('prop1.component_weight', 'prop1_weight')

        #connect design variables to model component inputs
        self.connect('eng_rating', 'eng1.shaft_power_rating')
        self.connect('prop_diameter', ['prop1.diameter'])
        self.connect('motor_rating', ['motor1.elec_power_rating'])
        self.connect('motor_rating', ['prop1.power_rating'])
        self.connect('gen_rating', 'gen1.elec_power_rating')
        self.connect('batt_weight', 'batt1.battery_weight')

class TwinSeriesHybridElectricPropulsionSystem(Group):
    """This is an example model of a series-hybrid propulsion system. One motor
        draws electrical load from two sources in a fractional split| a battery pack,
        and a turbogenerator setup. The control inputs are the power split fraction and the
        motor throttle setting; the turboshaft throttle matches the power level necessary
        to drive the generator at the required power level.

        Fuel flows and prop thrust should be fairly accurate. Heat constraints haven't yet been incorporated.

        The "pilot" controls thrust by varying the motor throttles from 0 to 100+% of rated power. She may also vary the percentage of battery versus fuel being used
        by varying the power_split_fraction

        This module alone cannot produce accurate fuel flows, battery loads, etc. You must do the following, either with an implicit solver or with the optimizer:
        - Set eng1.throttle such that gen1.elec_power_out = hybrid_split.power_out_A

        The battery does not track its own state of charge (SOC); it is connected to elec_load simply so that the discharge rate can be compared to the discharge rate capability of the battery.
        SOC and fuel flows should be time-integrated at a higher level (in the mission analysis codes)

        Arrows show flow of information. In openConcept, mechanical power operates on a 'push' basis, while electrical load operates on a 'pull' basis. We reconcile these flows across an implicit gap by driving a residual to 0 using a solver.

        eng1.throttle                                                           hybrid_split.power_split_fraction           motor1.throttle
            ||                                                                                   ||                             ||
        eng1 --shaft_power_out--> gen1 --elec_power_out--> {IMPLICIT GAP} <--power_out_B         ||           <--elec_load-- motor1 --shaft_power_out --> prop1 -->thrust
           ||                                                                             hybrid_split <--elec_load  ++
           ||                                            batt1.elec_load <--power_out_A                       <--elec_load-- motor2 --shaft_power_out --> prop2 -->thrust
            V                                                                   V                                              ||
        fuel_flow (integrate over time)                                   elec_load (integrate over time to obtain SOC)       motor2.throttle


    """
    def initialize(self):
        self.options.declare('num_nodes',default=1,desc="Number of mission analysis points to run")
        self.options.declare('specific_energy',default=300,desc="Battery spec energy in Wh/kg")


    def setup(self):
        #define design variables that are independent of flight condition or control states
        dvlist = [['ac|propulsion|engine|rating','eng_rating',260.0,'kW'],
                    ['ac|propulsion|propeller|diameter','prop_diameter',2.5,'m'],
                    ['ac|propulsion|motor|rating','motor_rating',240.0,'kW'],
                    ['ac|propulsion|generator|rating','gen_rating',250.0,'kW'],
                    ['ac|weights|W_battery','batt_weight',2000,'kg']]
        self.add_subsystem('dvs',DVLabel(dvlist),promotes_inputs=["*"],promotes_outputs=["*"])
        nn = self.options['num_nodes']
        e_b = self.options['specific_energy']
        #introduce model components
        self.add_subsystem('motor1', SimpleMotor(efficiency=0.97,num_nodes=nn))
        self.add_subsystem('prop1',SimplePropeller(num_nodes=nn),promotes_inputs=["fltcond|*"])
        self.connect('motor1.shaft_power_out','prop1.shaft_power_in')


        self.add_subsystem('motor2', SimpleMotor(efficiency=0.97,num_nodes=nn))
        self.add_subsystem('prop2',SimplePropeller(num_nodes=nn),promotes_inputs=["fltcond|*"])
        self.connect('motor2.shaft_power_out','prop2.shaft_power_in')

        addpower = AddSubtractComp(output_name='motors_elec_load',input_names=['motor1_elec_load','motor2_elec_load'], units='kW',vec_size=nn)
        addpower.add_equation(output_name='thrust',input_names=['prop1_thrust','prop2_thrust'], units='N',vec_size=nn)
        self.add_subsystem('add_power',subsys=addpower,promotes_outputs=['*'])
        self.connect('motor1.elec_load','add_power.motor1_elec_load')
        self.connect('motor2.elec_load','add_power.motor2_elec_load')
        self.connect('prop1.thrust','add_power.prop1_thrust')
        self.connect('prop2.thrust','add_power.prop2_thrust')

        self.add_subsystem('hybrid_split',PowerSplit(rule='fraction',num_nodes=nn))
        self.connect('motors_elec_load','hybrid_split.power_in')

        self.add_subsystem('eng1',SimpleTurboshaft(num_nodes=nn,weight_inc=0.14/1000,weight_base=104),promotes_outputs=["fuel_flow"])
        self.add_subsystem('gen1',SimpleGenerator(efficiency=0.97,num_nodes=nn))

        self.connect('eng1.shaft_power_out','gen1.shaft_power_in')

        self.add_subsystem('batt1',SimpleBattery(num_nodes=nn,specific_energy=e_b))
        self.connect('hybrid_split.power_out_A','batt1.elec_load')
        self.add_subsystem('eng_gen_resid',AddSubtractComp(output_name='eng_gen_residual',input_names=['gen_power_available','gen_power_required'],vec_size=nn, units='kW',scaling_factors=[1,-1]))
        #need to use the optimizer to drive hybrid_split.power_out_B to the same value as gen1.elec_power_out
        self.connect('hybrid_split.power_out_B','eng_gen_resid.gen_power_required')
        self.connect('gen1.elec_power_out','eng_gen_resid.gen_power_available')
        addweights = AddSubtractComp(output_name='motors_weight',input_names=['motor1_weight','motor2_weight'], units='kg')
        addweights.add_equation(output_name='propellers_weight',input_names=['prop1_weight','prop2_weight'], units='kg')
        self.add_subsystem('add_weights',subsys=addweights,promotes_inputs=['*'],promotes_outputs=['*'])
        self.connect('motor1.component_weight','motor1_weight')
        self.connect('motor2.component_weight','motor2_weight')
        self.connect('prop1.component_weight','prop1_weight')
        self.connect('prop2.component_weight','prop2_weight')

        #connect design variables to model component inputs
        self.connect('eng_rating','eng1.shaft_power_rating')
        self.connect('prop_diameter',['prop1.diameter','prop2.diameter'])
        self.connect('motor_rating',['motor1.elec_power_rating','motor2.elec_power_rating'])
        self.connect('motor_rating',['prop1.power_rating','prop2.power_rating'])
        self.connect('gen_rating','gen1.elec_power_rating')
        self.connect('batt_weight','batt1.battery_weight')


class VehicleSizingModel(Group):
    def setup(self):
        dvs = self.add_subsystem('dvs',IndepVarComp(),promotes_outputs=["*"])
        climb = self.add_subsystem('missionanalysis',MissionAnalysis(),promotes_inputs=["dv_*"])
        dvs.add_output('dv_prop1_diameter',3.0, units='m')
        dvs.add_output('dv_motor1_rating',1.5, units='MW')
        dvs.add_output('dv_gen1_rating',1.55, units='MW')
        dvs.add_output('ac|propulsion|engine|rating',1.6, units='MW')
        dvs.add_output('dv_batt1_weight',2000, units='kg')



if __name__ == "__main__":

    from openconcept.simple_series_hybrid import VehicleSizingModel as VSM
    prob = Problem()

    prob.model= VSM()

    prob.setup()
    prob.run_model()

    # print "------Prop 1-------"
    print('Thrust: ' + str(prob['missionanalysis.propmodel.prop1.thrust']))
    plt.plot(prob['missionanalysis.propmodel.prop1.thrust'])
    plt.show()

    print('Weight: ' + str(prob['missionanalysis.propmodel.prop1.component_weight']))

    # print'Prop eff: ' + str(prob['prop1.eta_prop'])

    # print "------Motor 1-------"
    # print 'Shaft power: ' + str(prob['motor1.shaft_power_out'])
    # print 'Elec load: ' + str(prob['motor1.elec_load'])
    # print 'Heat: ' + str(prob['motor1.heat_out'])


    # print "------Battery-------"
    # print 'Elec load: ' + str(prob['batt1.elec_load'])
    # print 'Heat: ' + str(prob['batt1.heat_out'])


    # print "------Generator-------"
    # print 'Shaft power: ' + str(prob['gen1.shaft_power_in'])
    # print 'Elec load: ' + str(prob['gen1.elec_power_out'])
    # print 'Heat: ' + str(prob['gen1.heat_out'])

    # print "------Turboshaft-------"
    # print 'Throttle: '  + str(prob['eng1.throttle'])
    # print 'Shaft power: ' + str(prob['eng1.shaft_power_out'])
    # print 'Fuel flow:' + str(prob['eng1.fuel_flow']*60*60)

    #prob.model.list_inputs()
    #prob.model.list_outputs()
    #prob.check_partials(compact_print=True)
    #prob.check_totals(compact_print=True)
