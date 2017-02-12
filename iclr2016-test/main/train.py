from collections import defaultdict
from itertools import count

import nltk, math

from params import params
import ppdb_utils
import lasagne
import random
import numpy as np
import sys, os
import argparse

new_path = '../similarity'
if new_path not in sys.path:
    sys.path.append(new_path)

from lstm_model_sim import lstm_model_sim
from proj_model_sim import proj_model_sim
from word_model_sim import word_model_sim
from dan_model_sim import dan_model_sim
from rnn_model_sim import rnn_model_sim

import utils

def str2bool(v):
    if v is None:
        return False
    if v.lower() in ("yes", "true", "t", "1"):
        return True
    if v.lower() in ("no", "false", "f", "0"):
        return False
    raise ValueError('A type that was supposed to be boolean is not boolean.')

def learner2bool(v):
    if v is None:
        return lasagne.updates.adam
    if v.lower() == "adagrad":
        return lasagne.updates.adagrad
    if v.lower() == "adam":
        return lasagne.updates.adam
    if v.lower() == "adadelta":
        return lasagne.updates.adadelta
    raise ValueError('A type that was supposed to be a learner is not.')

random.seed(1)
np.random.seed(1)

params = params()

parser = argparse.ArgumentParser()
parser.add_argument("-LW", help="Lambda for word embeddings (normal training).", type=float)
parser.add_argument("-LC", help="Lambda for composition parameters (normal training).", type=float)
parser.add_argument("-outfile", help="Output file name.")
parser.add_argument("-batchsize", help="Size of batch.", type=int)
parser.add_argument("-dim", help="Size of input.", type=int)
parser.add_argument("-memsize", help="Size of classification layer.",
                    type=int)
parser.add_argument("-wordfile", help="Word embedding file.")
parser.add_argument("-layersize", help="Size of output layers in models.", type=int)
parser.add_argument("-updatewords", help="Whether to update the word embeddings")
parser.add_argument("-wordstem", help="Nickname of word embeddings used.")
parser.add_argument("-save", help="Whether to pickle the model.")
parser.add_argument("-traindata", help="Training data file.")
parser.add_argument("-devdata", help="Training data file.")
parser.add_argument("-testdata", help="Testing data file.")
parser.add_argument("-peephole", help="Whether to use peephole connections in LSTM.")
parser.add_argument("-outgate", help="Whether to use output gate in LSTM.")
parser.add_argument("-nonlinearity", help="Type of nonlinearity in projection and DAN model.",
                    type=int)
parser.add_argument("-nntype", help="Type of neural network.")
parser.add_argument("-evaluate", help="Whether to evaluate the model during training.")
parser.add_argument("-epochs", help="Number of epochs in training.", type=int)
parser.add_argument("-regfile", help="Path to model file that we want to regularize towards.")
parser.add_argument("-minval", help="Min rating possible in scoring.", type=int)
parser.add_argument("-maxval", help="Max rating possible in scoring.", type=int)
parser.add_argument("-LRW", help="Lambda for word embeddings (regularization training).", type=float)
parser.add_argument("-LRC", help="Lambda for composition parameters (regularization training).", type=float)
parser.add_argument("-traintype", help="Either normal, reg, or rep.")
parser.add_argument("-clip", help="Threshold for gradient clipping.",type=int)
parser.add_argument("-eta", help="Learning rate.", type=float)
parser.add_argument("-learner", help="Either AdaGrad or Adam.")
parser.add_argument("-task", help="Either sim, ent, or sentiment.")
parser.add_argument("-numlayers", help="Number of layers in DAN Model.", type=int)

args = parser.parse_args()

params.LW = args.LW
params.LC = args.LC
params.outfile = args.outfile
params.batchsize = args.batchsize
params.hiddensize = args.dim
params.memsize = args.memsize
params.wordfile = args.wordfile
params.nntype = args.nntype
params.layersize = args.layersize
params.updatewords = str2bool(args.updatewords)
params.wordstem = args.wordstem
params.save = str2bool(args.save)
params.traindata = args.traindata
params.devdata = args.devdata
params.testdata = args.testdata
params.usepeep = str2bool(args.peephole)
params.useoutgate = str2bool(args.outgate)
params.nntype = args.nntype
params.epochs = args.epochs
params.traintype = args.traintype
params.evaluate = str2bool(args.evaluate)
params.LRW = args.LRW
params.LRC = args.LRC
params.learner = learner2bool(args.learner)
params.task = args.task
params.numlayers = args.numlayers

if args.eta:
    params.eta = args.eta

params.clip = args.clip
if args.clip:
    if params.clip == 0:
        params.clip = None

params.regfile = args.regfile
params.minval = args.minval
params.maxval = args.maxval

if args.nonlinearity:
    if args.nonlinearity == 1:
        params.nonlinearity = lasagne.nonlinearities.linear
    if args.nonlinearity == 2:
        params.nonlinearity = lasagne.nonlinearities.tanh
    if args.nonlinearity == 3:
        params.nonlinearity = lasagne.nonlinearities.rectify
    if args.nonlinearity == 4:
        params.nonlinearity = lasagne.nonlinearities.sigmoid

# (words, We) = ppdb_utils.getWordmap(params.wordfile)

words=None
if args.task == "sim" or args.task == "ent":
    train_data = ppdb_utils.getSimEntDataset(params.traindata,words,params.task)
    dev_data = ppdb_utils.getSimEntDataset(params.devdata, words, params.task)

    data_dir = '../data/eval'
    files = os.listdir(data_dir)

    for file in files:
        path = data_dir + '/' + file
        if 'track' in path:
            print(path)
            dev_data += ppdb_utils.getSimEntDataset(path, words, params.task)

elif args.task == "sentiment":
    train_data = ppdb_utils.getSentimentDataset(params.traindata,words)
else:
    raise ValueError('Task should be ent, sim, or sentiment.')

class Vocab:
    def __init__(self, w2i=None):
        if w2i is None: w2i = defaultdict(count(0).next)
        self.w2i = dict(w2i)
        self.i2w = {i: w for w, i in w2i.iteritems()}

    @classmethod
    def from_corpus(cls, corpus):
        w2i = defaultdict(count(0).next)
        for sent in corpus:
            [w2i[word] for word in sent]
        return Vocab(w2i)

    def fw2i(self, word):
        if word not in self.w2i:
            return self.w2i['_UNK_']
        else:
            return self.w2i[word]

    def size(self):
        return len(self.w2i.keys())

def IDFCalculator(sequence_list, min_cnt=1):
    doc_num = 0
    word_list = []
    for sequence in sequence_list:
        word_list += sequence
        doc_num += 1

    vdist = nltk.FreqDist(word_list)
    idf_dict = {}
    good_keys = [v for v in vdist.keys() if vdist[v] >= min_cnt]

    for key in good_keys:
        idf_dict[key] = vdist[key]

    for key in idf_dict.keys():
        idf_dict[key] = math.log(float(doc_num) / float(idf_dict[key])) / math.log(10)

    return idf_dict

words = []
for example in train_data + dev_data:  # TODO add test_data
    phrase = example[0].phrase.lower()
    arr = phrase.split()
    words.append(arr)
    phrase = example[1].phrase.lower()
    arr = phrase.split()
    words.append(arr)


idf_dict = IDFCalculator(words)

words.append(["UUUNKKK"])
idf_dict["UUUNKKK"] = min(idf_dict.values())

vw = Vocab.from_corpus(words)
words = vw.w2i
if 'word2vec' in params.wordfile:
    We = ppdb_utils.load_w2v_offline(words)
elif 'paragram' in params.wordfile:
    We = ppdb_utils.load_embedding_offline(words)

for w in words:
    wid = words[w]
    We[wid] = idf_dict[w] * We[wid]

model = None

print sys.argv

if params.nntype == 'lstm':
    model = lstm_model_sim(We, params)
elif params.nntype == 'word':
    model = word_model_sim(We, params)
elif params.nntype == 'proj':
    model = proj_model_sim(We, params)
elif params.nntype == 'dan':
    model = dan_model_sim(We, params)
elif params.nntype == 'rnn':
    model = rnn_model_sim(We, params)
else:
    "Error no type specified"

utils.train(model, train_data, params.devdata, params.testdata, params.traindata, words, params)


data_dir = '../data/eval'
files = os.listdir(data_dir)

for file in files:
    path = data_dir + '/' + file
    utils.test(model, path, words, params)


