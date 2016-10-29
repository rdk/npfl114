from __future__ import division
from __future__ import print_function

import datetime
import math
import numpy as np
import tensorflow as tf
import tensorflow.contrib.layers as tf_layers
import tensorflow.contrib.losses as tf_losses
import tensorflow.contrib.metrics as tf_metrics

class Network:
    WIDTH = 28
    HEIGHT = 28
    LABELS = 10

    def __init__(self, threads=1, logdir=None, expname=None, seed=42):
        # Create an empty graph and a session
        graph = tf.Graph()
        graph.seed = seed
        self.session = tf.Session(graph = graph, config=tf.ConfigProto(inter_op_parallelism_threads=threads,
                                                                       intra_op_parallelism_threads=threads))

        if logdir:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
            self.summary_writer = tf.train.SummaryWriter(("{}/{}-{}" if expname else "{}/{}").format(logdir, timestamp, expname), flush_secs=10)
        else:
            self.summary_writer = None

    def construct(self, hidden_layer,optimizer):
        with self.session.graph.as_default():
            with tf.name_scope("inputs"):
                self.images = tf.placeholder(tf.float32, [None, self.WIDTH, self.HEIGHT, 1], name="images")
                self.labels = tf.placeholder(tf.int64, [None], name="labels")

            flattened_images = tf_layers.flatten(self.images, scope="preprocessing")
            hidden_layer = tf_layers.fully_connected(flattened_images, num_outputs=hidden_layer, activation_fn=tf.nn.relu, scope="hidden_layer")
            output_layer = tf_layers.fully_connected(hidden_layer, num_outputs=self.LABELS, activation_fn=None, scope="output_layer")
            self.predictions = tf.argmax(output_layer, 1)

            loss = tf_losses.sparse_softmax_cross_entropy(output_layer, self.labels, scope="loss")
            self.training = optimizer.minimize(loss, global_step=self.global_step)
            self.accuracy = tf_metrics.accuracy(self.predictions, self.labels)

            # Summaries
            self.summaries = {"training": tf.merge_summary([tf.scalar_summary("train/loss", loss),
                                                            tf.scalar_summary("train/accuracy", self.accuracy)])}
            for dataset in ["dev", "test"]:
                self.summaries[dataset] = tf.scalar_summary(dataset+"/accuracy", self.accuracy)

            # Initialize variables
            self.session.run(tf.initialize_all_variables())

        # Finalize graph and log it if requested
        self.session.graph.finalize()
        if self.summary_writer:
            self.summary_writer.add_graph(self.session.graph)

    @property
    def training_step(self):
        return self.session.run(self.global_step)

    def train(self, images, labels, summaries=False, run_metadata=False):
        if (summaries or run_metadata) and not self.summary_writer:
            raise ValueError("Logdir is required for summaries or run_metadata.")

        args = {"feed_dict": {self.images: images, self.labels: labels}}
        targets = [self.training]
        if summaries:
            targets.append(self.summaries["training"])
        if run_metadata:
            args["options"] = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
            args["run_metadata"] = tf.RunMetadata()

        results = self.session.run(targets, **args)
        if summaries:
            self.summary_writer.add_summary(results[-1], self.training_step - 1)
        if run_metadata:
            self.summary_writer.add_run_metadata(args["run_metadata"], "step{:05}".format(self.training_step - 1))

    def evaluate(self, dataset, images, labels, summaries=False):
        if summaries and not self.summary_writer:
            raise ValueError("Logdir is required for summaries.")

        targets = [self.accuracy]
        if summaries:
            targets.append(self.summaries[dataset])

        results = self.session.run(targets, {self.images: images, self.labels: labels})
        if summaries:
            self.summary_writer.add_summary(results[-1], self.training_step)
        return results[0]


if __name__ == "__main__":
    # Fix random seed
    np.random.seed(42)

    # Parse arguments
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch_size", default=1, type=int, help="Batch size.")
    parser.add_argument("--epochs", default=20, type=int, help="Number of epochs.")
    parser.add_argument("--logdir", default="logs", type=str, help="Logdir name.")
    parser.add_argument("--exp", default="4-mnist-using-contrib", type=str, help="Experiment name.")
    parser.add_argument("--threads", default=1, type=int, help="Maximum number of threads to use.")
    args = parser.parse_args()


    # Construct the network
    allOptimizers = []
    for learningRate in [0.01,0.001,0.0001]:
        allOptimizers.append((tf.train.GradientDescentOptimizer(learningRate),"SGD {}".format(learningRate)) )

    for learningRate in [0.01,0.001,0.0001]:
        allOptimizers.append((tf.train.MomentumOptimizer(learningRate,0.9),"Moment {}".format(learningRate)))

    for learningRate in [0.002,0.001,0.0005]:
        allOptimizers.append((tf.train.AdamOptimizer(learning_rate = learningRate),"Adam {}".format(learningRate)))


    results = []
    for (optimizer,nameOpt) in allOptimizers:
        for batchsize in [50,10,1]:
            # Load the data
            from tensorflow.examples.tutorials.mnist import input_data
            mnist = input_data.read_data_sets("mnist_data/", reshape=False)
            exp_name = "{}-{}".format(batchsize, nameOpt)
            network = Network(threads=args.threads, logdir=args.logdir, expname=exp_name)
            with network.session.graph.as_default():
                network.global_step = tf.Variable(0, dtype=tf.int64, trainable=False, name="global_step")
            network.construct(100,optimizer)
            # Train
            dev_acc = 0;
            test_acc = 0;
            for i in range(args.epochs):
                while mnist.train.epochs_completed == i:
                    images, labels = mnist.train.next_batch(batchsize)
                    network.train(images, labels, network.training_step % 100 == 0, network.training_step == 0)

                dev_acc = network.evaluate("dev", mnist.validation.images, mnist.validation.labels, True)
                test_acc = network.evaluate("test", mnist.test.images, mnist.test.labels, True)
            results.append((exp_name, dev_acc, test_acc))
            print(results[-1])


    for (startRate,endRate) in [(0.01,0.001), (0.01,0.0001), (0.001, 0.0001)]:
        for batchsize in [50,10,1]:
            # Load the data
            from tensorflow.examples.tutorials.mnist import input_data
            mnist = input_data.read_data_sets("mnist_data/", reshape=False)

            exp_name = "{}-decay {}, {}".format(batchsize, startRate,endRate)
            network = Network(threads=args.threads, logdir=args.logdir, expname=exp_name)
            with network.session.graph.as_default():
                network.global_step = tf.Variable(0, dtype=tf.int64, trainable=False, name="global_step")
            total_steps = (mnist.train.images.size/batchsize) *args.epochs
            network.construct(100,tf.train.GradientDescentOptimizer(tf.train.exponential_decay(startRate,network.global_step,1,math.pow(endRate/startRate,1/total_steps))))
            # Train
            dev_acc = 0;
            test_acc = 0;
            for i in range(args.epochs):
                while mnist.train.epochs_completed == i:
                    images, labels = mnist.train.next_batch(batchsize)
                    network.train(images, labels, network.training_step % 100 == 0, network.training_step == 0)

                dev_acc = network.evaluate("dev", mnist.validation.images, mnist.validation.labels, True)
                test_acc = network.evaluate("test", mnist.test.images, mnist.test.labels, True)
            results.append((exp_name, dev_acc, test_acc))
            print(results[-1])

    best = max(results, key=lambda x: x[1])
    print("Best hyperparams: {}, dev_acc: {}, test_acc: {}".format(best[0], best[1], best[2]))
