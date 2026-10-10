## learning_rate
- p16 `512` | 页内表串列=False | 跨页表串列=False | 参考文献=False | 语境否决=—
    左20='formula: lrscaled =\n'
    右30=' × batchsize, similarly to Goy'
- p16 `0.003` | 页内表串列=True | 跨页表串列=True | 参考文献=False | 语境否决=—
    左20='timizer\nAdamW\nAdamW\n'
    右30='\n0.0005 × batchsize\n512\nLearni'

## batch_size
- p16 `4096` | 页内表串列=True | 跨页表串列=True | 参考文献=False | 语境否决=—
    左20='iT-B\nEpochs\n300\n300\n'
    右30='\n1024\nOptimizer\nAdamW\nAdamW\nle'
- p16 `512` | 页内表串列=False | 跨页表串列=False | 参考文献=False | 语境否决=—
    左20='rate\n0.003\n0.0005 × '
    右30='\nLearning rate decay\ncosine\nco'
