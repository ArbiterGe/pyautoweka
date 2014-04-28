import xml.etree.ElementTree as ET
import xml.dom.minidom
from subprocess import call, check_output
import numpy as np
import datetime
import os
import imp

from pkg_resources import resource_filename

"""
DEVELOPMENT NOTES

 * API for getting experiment results

 * API for running + training + predicting

 * auto-wekalight doesn't work: 
            java -cp "./lib/weka.jar;autoweka-light.jar" autoweka.ExperimentConstructor experiments/experiment.xml
            Error: Could not find or load main class autoweka.ExperimentConstructor

 * write the data to python temporary files that will later on be deleted...

"""


EXPERIMENT_BASE_FOLDER = "experiments"

def get_available_classifiers():
    """
        Determine the available classifiers by iterating over
        all parameter files.
    """
    params_dir = resource_filename(__name__, 'java/params')
    classifiers = []
    for root, dir, files in os.walk(params_dir):
        for file in files:
            if file.startswith("weka.classifiers") and file.endswith(".params"):
                clf = file[0:-len(".params")]
                classifiers.append(clf)
    return classifiers

AVAILABLE_CLASSIFIERS = get_available_classifiers()

def run_program(cmd, hide_output=False):
    if hide_output:
        ret = call(cmd,
             stdout=open(os.devnull),
             stderr=open(os.devnull))
    else:
        ret = call(cmd)
    return ret

def arff_write(fname, name, X, y, feature_names=None):
    """
    Write out an arff file based on X and y.
    """
    unique_labels = list(set(y))
    nexamples = len(X[0])
    if feature_names == None:
        feature_names = ["feature%d" % i for i in xrange(0,nexamples)]
    with open(fname, 'w') as fout:
        fout.write("@RELATION %s\n" % name)
        for feature_name in feature_names:
            fout.write("@ATTRIBUTE %s REAL\n" % feature_name)
        fout.write("@ATTRIBUTE class {%s}\n" % ", ".join([str(x) for x in unique_labels]))
        fout.write("@DATA\n")
        for row, label in zip(X, y):
            for value in row:
                fout.write(str(value))
                fout.write(",")
            fout.write(str(label))
            fout.write("\n")


class InstanceGenerator(object):
    def __init__(self):
        self.name = "Default"
        self.params = {}

    def get_arg_str(self):
        key_value_str = lambda key, value: "%s=%s" % (str(key), str(value))
        return ":".join([key_value_str(key, value)
                         for key, value in self.params.iteritems()])


class CrossValidation(InstanceGenerator):
    """
    Performs k-fold cross validation on the training set.
    """
    def __init__(self, seed=0, num_folds=10):
        """
        :param seed: The seed to use for randomizing the dataset
        :param num_fold./s: The number of folds to generate
        """
        super(CrossValidation, self).__init__()
        self.name = "autoweka.instancegenerators.CrossValidation"
        self.params["seed"] = seed
        self.params["numFolds"] = num_folds


class RandomSubSampling(InstanceGenerator):
    """
    Performs generates an arbitrary number of folds by randomly
    making a partition of the training data of a fixed percentage.
    """
    def __init__(self, starting_seed=0, num_samples=10,
                 percent_training=70, bias_to_uniform=None):
        """

        :param starting_seed: The seed to use for randomizing the dataset
        :param num_samples: The number of subsamples to generate
        :param percent_training: The percent of the training data to use
        as 'new training data'
        :param bias_to_uniform: The bias towards a uniform class
        distribution (optional)
        """
        super(RandomSubSampling, self).__init__()
        self.name = "autoweka.instancegenerators.RandomSubSampling"
        self.params["startingSeed"] = starting_seed
        self.params["numSamples"] = num_samples
        self.params["percent"] = percent_training
        if bias_to_uniform:
            self.params["bias"] = bias_to_uniform


class DataSet(object):
    def __init__(self, train_file, test_file=None, name="data"):
        """
        Dataset.

        :param train_file: ARFF file containing the training data
        :param test_file: ARFF file containing the testing data, that will be
        used once the experiment completed (optional)
        :param name: name of the dataset (optional)
        """
        self.train_file = os.path.abspath(train_file)
        if test_file:
            self.test_file = os.path.abspath(test_file)
        else:
            self.test_file = None
        self.name = name


class Experiment:

    RESULT_METRICS = ["errorRate",
                      "rmse",
                      "rrse",
                      "meanAbsoluteErrorMetric",
                      "relativeAbsoluteErrorMetric"]

    OPTIMIZATION_METHOD = ["SMAC", "TPE"]

    OPTIMIZATION_METHOD_CONSTRUCTOR = {
        "SMAC": "autoweka.smac.SMACExperimentConstructor",
        "TPE":  "autoweka.tpe.TPEExperimentConstructor"}

    OPTIMIZATION_METHOD_ARGS = {
        "SMAC": [
            "-experimentpath", os.path.abspath(EXPERIMENT_BASE_FOLDER),
            "-propertyoverride",
            ("smacexecutable=%s" % (resource_filename(__name__, 'java/smac-v2.04.01-master-447-patched/smac.sh')))
            ],
        #TODO: fix the TPE paths
        "TPE": [
            "-experimentpath", os.path.abspath(EXPERIMENT_BASE_FOLDER),
            "-propertyoverride",
            ("pythonpath=$PYTHONPATH\:~/src/hyperopt\:~/src/hyperopt/external:"
             "tperunner=./src/python/tperunner.py:python=/usr/bin/python2")
            ]
        }

    OPTIMIZATION_METHOD_EXTRA = {
        "SMAC": "executionMode=SMAC:initialIncumbent=RANDOM:initialN=1",
        "TPE": ""
        }

    def __init__(
            self,
            experiment_name="Experiment",
            result_metric=RESULT_METRICS[0],
            optimization_method=OPTIMIZATION_METHOD[0],
            instance_generator=None,
            tuner_timeout=180,
            train_timeout=120,
            attribute_selection=True,
            attribute_selection_timeout=100,
            memory="3000m"
            ):
        """
        Create a new experiment.

        :param tuner_timeout: The number of seconds to run the SMBO method.
        :param train_timeout: The number of seconds to spend training
        a classifier with a set of hyperparameters on a given partition of
        the training set.
        """
        if result_metric not in Experiment.RESULT_METRICS:
            raise ValueError("%s is not a valid result metric,"
                             " choose one from: %s" % (
                                 result_metric,
                                 ", ".join(Experiment.RESULT_METRICS)))

        if optimization_method not in Experiment.OPTIMIZATION_METHOD:
            raise ValueError("%s is not a valid optimization method,"
                             " choose one from:" % (
                                 optimization_method,
                                 ", ".join(Experiment.OPTIMIZATION_METHOD)))

        if (instance_generator
                and not isinstance(instance_generator, InstanceGenerator)):
            raise ValueError(("instance_generator needs to be"
                              " an InstanceGenerator or None"))

        if not isinstance(attribute_selection, bool):
            raise ValueError("attribute_selection needs to be a boolean")

        self.experiment_name = experiment_name
        self.result_metric = result_metric
        self.optimization_method = optimization_method
        self.instance_generator = instance_generator
        self.tuner_timeout = tuner_timeout
        self.train_timeout = train_timeout
        self.attribute_selection = attribute_selection
        self.attribute_selection_timeout = attribute_selection_timeout
        self.memory = memory

        self.datasets = []
        self.classifiers = []

        self.file_name = None

        self.prepared = False

    def _get_xml(self):
        """
        Write this experiment as a valid xml that can be read by Auto-WEKA.
        """

        root = ET.Element('experimentBatch')
        tree = ET.ElementTree(root)

        experiment = ET.SubElement(root, 'experimentComponent')

        name_node = ET.SubElement(experiment, 'name')
        name_node.text = self.experiment_name

        result_metric_node = ET.SubElement(experiment, 'resultMetric')
        result_metric_node.text = self.result_metric

        experiment_constructor = ET.SubElement(experiment,
                                               'experimentConstructor')
        experiment_constructor.text = Experiment.OPTIMIZATION_METHOD_CONSTRUCTOR[
            self.optimization_method]
        for experiment_arg in Experiment.OPTIMIZATION_METHOD_ARGS[
                self.optimization_method]:
            experiment_arg_node = ET.SubElement(experiment,
                                                'experimentConstructorArgs')
            experiment_arg_node.text = experiment_arg

        extra_props_node = ET.SubElement(experiment, 'extraProps')
        extra_props_node.text = Experiment.OPTIMIZATION_METHOD_EXTRA[
            self.optimization_method]

        instance_generator_node = ET.SubElement(experiment,
                                                'instanceGenerator')
        if not self.instance_generator:
            #Default generator
            instance_generator_node.text = "autoweka.instancegenerators.Default"
            instance_generator_args_node = ET.SubElement(
                experiment,
                'instanceGeneratorArgs')
            instance_generator_args_node.text = ""
        else:
            instance_generator_node.text = self.instance_generator.name
            instance_generator_args_node = ET.SubElement(
                experiment,
                'instanceGeneratorArgs')
            instance_generator_args_node.text = self.instance_generator.get_arg_str()

        tuner_timeout_node = ET.SubElement(experiment, 'tunerTimeout')
        tuner_timeout_node.text = str(self.tuner_timeout)
        train_timeout_node = ET.SubElement(experiment, 'trainTimeout')
        train_timeout_node.text = str(self.train_timeout)

        attribute_selection_node = ET.SubElement(experiment, 'attributeSelection')
        if self.attribute_selection:
            attribute_selection_node.text = "true"
            attr_select_timeout_node = ET.SubElement(
                experiment, 'attributeSelectionTimeout')
            attr_select_timeout_node.text = str(self.attribute_selection_timeout)
        else:
            attribute_selection_node.text = "false"

        for classifier in self.classifiers:
            classifier_node = ET.SubElement(experiment, 'allowedClassifiers')
            classifier_node.text = classifier

        memory_node = ET.SubElement(experiment, 'memory')
        memory_node.text = str(self.memory)

        # Write all dataset components:

        for dataset in self.datasets:
            dataset_node = ET.SubElement(root, 'datasetComponent')
            train_file_node = ET.SubElement(dataset_node, 'trainArff')
            train_file_node.text = dataset.train_file
            test_file_node = ET.SubElement(dataset_node, 'testArff')
            if dataset.test_file:
                test_file_node.text = dataset.test_file
            else:
                #train_file not set, so use the train file again
                test_file_node.text = dataset.train_file
            name_node = ET.SubElement(dataset_node, 'name')
            name_node.text = dataset.name

        return tree

    def __repr__(self):
        root = self._get_xml().getroot()
        return xml.dom.minidom.parseString(ET.tostring(root)).toprettyxml()

    def _write_xml(self, file_name="experiment.xml"):
        tree = self._get_xml()
        self.file_name = file_name
        tree.write(file_name)

    def set_data_set(self,
                     train_data,
                     train_labels,
                     test_data=None,
                     test_labels=None,
                     feature_names=None,
                     name="dataset1"):
        """
        Add a dataset that the experiment will be run on.
        (For now only one dataset per experiment is supported)

        :param train_data: training data as a 2 dimensional list, examples x features
        :param test_data: test data as a 2 dimensional list, examples x features
        :param feature_names: the name of each feature
        :param name: the name of the dataset
        """
        fname_train = name + "_train.arff"
        if test_data and test_labels:
            fname_test = name + "_test.arff"
            #add the labels as the last column to the test data:
            test_data = np.asarray(test_data)
            test_labels = np.asarray(test_labels)
            test_combined = np.append(test_data,test_labels[:,None],1)
        else:
            fname_test = None

        #add the labels as the last column to the train data:
        train_data = np.asarray(train_data)
        train_labels = np.asarray(train_labels)
        #train_combined = np.append(train_data,train_labels[:,None],1)
 
        #arff.dump(fname_train, train_combined, relation=name)
        arff_write(fname_train, name, train_data, train_labels, feature_names)
        if fname_test:
            #arff.dump(fname_test, test_combined, relation=name)
            arff_write(fname_test, name, test_data, test_labels, feature_names)

        self.datasets = [DataSet(fname_train, fname_test, name)]

    def set_data_set_files(self, train_file, test_file=None, name=None):
        """
        Add a dataset to the experiment.
        (For now only on dataset per experiment is supported)

        :param train_file: ARFF file containing the training data
        :param test_file: ARFF file containing the testing data, that will be
        used once the experiment completed (optional)
        :param name: name of the dataset (optional)
        """
        if not os.path.exists(train_file):
            raise Exception("train_file doesn't exist")
        if test_file is not None and not os.path.exists(test_file):
            raise Exception("test_file doesn't exist")
        if name == None:
            name = os.path.basename(train_file)
        #check there's not other dataset with the same name
        for dataset in self.datasets:
            if dataset.name == name:
                raise ValueError("A dataset with the name '%s', was already added." % name)
        self.datasets = [DataSet(train_file, test_file, name)]

    def add_classfier(self, clf):
        """
        Restrict the search to a certain classifier. Call multiple times to select more than one.
        If not called, all classifiers will be used.

        For a list of available classifiers see: pyautoweka.AVAILABLE_CLASSIFIERS

        :param clf: the classifier
        """
        if not clf in AVAILABLE_CLASSIFIERS:
            raise ValueError("%s is not one of the AVAILABLE_CLASSIFIERS." % clf)
        self.classifiers.append(clf)
        self.prepared = False

    def prepare(self, hide_output=True):
        """
        Creates the experiment folder.

        """
        if len(self.datasets) == 0:
            raise Exception("No datasets added yet, see Experiment.set_data_set")
        self._write_xml(self.experiment_name + ".xml")
        experiment_constructor = [ "java",
                                   "-cp",
                                   resource_filename(__name__, 'java/autoweka.jar'),
                                   "autoweka.ExperimentConstructor",
                                   self.file_name]
        ret = run_program(experiment_constructor, hide_output=hide_output)
        if ret == 0:
            #TODO: check return type for errors
            self.prepared = True
            return
        else:
            self.prepared = False
            raise Exception("Could not prepare the experiment")

    def run(self, seeds=[0], hide_output=True):
        """
            Run a experiment that was previously created

            :param seeds: a list of seeds for the random number generator
        """
        if not self.prepared:
            self.prepare()
        print "Running experiments"
        print "Time allocated(see Experiment.tuner_timeout): ", str(datetime.timedelta(seconds=self.tuner_timeout))
        for dataset in self.datasets:
            print "Running experiment on dataset %s" % dataset.name
            experiment_folder = self.get_experiment_folder(dataset)
            for seed in seeds:
                print "Running for seed %d" % seed
                experiment_runner = [ "java",
                                      "-cp",
                                      resource_filename(__name__, 'java/autoweka.jar'),
                                      "autoweka.tools.ExperimentRunner",
                                      experiment_folder,
                                      str(seed)]
                run_program(experiment_runner, hide_output=hide_output)
            #now let's merge the trajectories
            trajectory_merger = ["java",
                                  "-cp",
                                  resource_filename(__name__, 'java/autoweka.jar'),
                                  "autoweka.TrajectoryMerger",
                                  experiment_folder]
            print "Merging trajectories"
            run_program(trajectory_merger, hide_output=hide_output)

    def get_experiment_folder(self, dataset):
        experiment_folder = os.path.join(EXPERIMENT_BASE_FOLDER,
                                         self.experiment_name + "-" + dataset.name)
        return experiment_folder

    def get_best_seed_from_trajectories(self, dataset):
        experiment_folder = self.get_experiment_folder(dataset)

        trajectories_file = os.path.join(experiment_folder,
                                         self.experiment_name + "-" + dataset.name + ".trajectories")
        if not os.path.exists(trajectories_file):
            raise Exception("Trajectories file doesn't exist. Did you run the experiment?")
        best_trajectory_group = ["java",
                                 "-cp",
                                 resource_filename(__name__, 'java/autoweka.jar'),
                                 "autoweka.tools.GetBestFromTrajectoryGroup",
                                 trajectories_file]
        print " ".join(best_trajectory_group)
        program_output = str(check_output(best_trajectory_group))
        seed = -1
        for line in program_output.split("\n"):
            if line.startswith("Best point seed"):
                seed = int(line[len("Best point seed"):])
        if seed < 0:
            raise Exception("Failed getting seed")
        return seed

    def predict_from_file(self, data_file, predictions_file="out.csv", hide_output=False):
        """
        Make predictions on unseen data, using the best parameters.

        The predictions will be written in CSV format into predictions_file.
        TODO: predict from ndarray
        """
        #TODO: check the experiment has been run already
        if len(self.datasets) == 0:
            raise Exception("No datasets added yet, see Experiment.set_data_set")
        
        #TODO: for now we only support a single dataset
        dataset = self.datasets[0]
        seed = self.get_best_seed_from_trajectories(dataset)
        experiment_folder = self.get_experiment_folder(dataset)

        #TODO: what if there's not attribute selection
        prediction_runner = ["java",
                             "-cp",
                             resource_filename(__name__, 'java/autoweka.jar'),
                             "autoweka.tools.TrainedModelPredictionMaker",
                             "-model",
                             "%s/trained.%d.model" % (experiment_folder, seed),
                             "-attributeselection",
                             "%s/trained.%d.attributeselection" % (experiment_folder, seed),
                             "-dataset",
                             data_file,
                             "-predictionpath",
                             predictions_file]
        run_program(prediction_runner, hide_output=hide_output)

    def fit(X, y):
        """
        Fit a model to the data.

        X: array-like samples x features
        y: array-like labels
        """
        X = np.asarray(X)
        y = np.asarray(y)

        assert len(X.shape) == 2
        assert len(X.shape) == 1

        self.set_data_set(X,y)
        self.run()

    def fit_arff(file_name):
        self.set_data_set(file_name)
        self.run()

    def predict(X):
        pass

    def score(X, y):
        pass



