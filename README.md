pyautoweka
==========

Description
-----------

pyautoweka is a python wrapper for [Auto-WEKA](http://www.cs.ubc.ca/labs/beta/Projects/autoweka/), a Java application for algorithm selection and hyperparameter optimizations, that is build on [WEKA](http://www.cs.waikato.ac.nz/ml/weka/). 


Installation
------------

Go to the project sources and run:
```
python setup.py install
```

Running an experiment
--------------------

AutoWeka for python.

```python
import pyautoweka

#Create an experiment
experiment = pyautoweka.Experiment()

#Add some data to it
experiment.add_data_set("./datasets/creditg.arff")

#Run the experiment
experiment.run()
```


Advanced: Selecting specific classifiers
----------------------------------------

When you don't set a specific classifier all available classifiers will be tried. You have the option to limit the search to certain classifiers as follows:

First of all let's see what classifiers are available:

```python
import pyautoweka
print pyautoweka.AVAILABLE_CLASSIFIERS
```

Now let's say we want to just use the Simple Logistic classifier:
```python
experiment.add_classfier("weka.classifiers.functions.SimpleLogistic")
```

