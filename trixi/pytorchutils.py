import random
import warnings
from functools import lru_cache

import numpy as np
import torch


#@lru_cache(maxsize=32)
def get_vanilla_image_gradient(model, inpt, err_fn, abs=False):
    if isinstance(model, torch.nn.Module):
        model.zero_grad()
    inpt = inpt.detach()
    inpt.requires_grad = True

    # output = model(inpt)

    err = err_fn(inpt)
    err.backward()

    grad = inpt.grad.detach()

    if isinstance(model, torch.nn.Module):
        model.zero_grad()

    if abs:
        grad = torch.abs(grad)
    return grad.detach()


#@lru_cache(maxsize=32)
def get_guided_image_gradient(model: torch.nn.Module, inpt, err_fn, abs=False):
    def guided_relu_hook_function(module, grad_in, grad_out):
        if isinstance(module, (torch.nn.ReLU, torch.nn.LeakyReLU)):
            return (torch.clamp(grad_in[0], min=0.0),)

    model.zero_grad()

    ### Apply hooks
    hook_ids = []
    for mod in model.modules():
        hook_id = mod.register_backward_hook(guided_relu_hook_function)
        hook_ids.append(hook_id)

    inpt = inpt.detach()
    inpt.requires_grad = True

    # output = model(inpt)

    err = err_fn(inpt)
    err.backward()

    grad = inpt.grad.detach()

    model.zero_grad()
    for hooks in hook_ids:
        hooks.remove()

    if abs:
        grad = torch.abs(grad)
    return grad.detach()


#@lru_cache(maxsize=32)
def get_smooth_image_gradient(model, inpt, err_fn, abs=True, n_runs=20, eps=0.1,  grad_type="vanilla"):
    grads = []
    for i in range(n_runs):
        inpt = inpt + torch.randn(inpt.size()).to(inpt.device) * eps
        if grad_type == "vanilla":
            single_grad = get_vanilla_image_gradient(model, inpt, err_fn, abs=abs)
        elif grad_type == "guided":
            single_grad = get_guided_image_gradient(model, inpt, err_fn, abs=abs)
        else:
            warnings.warn("This grad_type is not implemented yet")
            single_grad = torch.zeros_like(inpt)
        grads.append(single_grad)

    grad = torch.mean(torch.stack(grads), dim=0)
    return grad.detach()


def get_input_gradient(model, inpt, err_fn, grad_type="vanilla", n_runs=20, eps=0.1,
                       abs=False, results_fn=lambda x, *y, **z: None):
    """
    Given a model creates calculates the error and backpropagates it to the image and saves it (saliency map).

    Args:
        model: The model to be evaluated
        inpt: Input to the model
        err_fn: The error function the evaluate the output of the model on
        grad_type: Gradient calculation method, currently supports (vanilla, vanilla-smooth, guided,
        guided-smooth) ( the guided backprob can lead to segfaults -.-)
        n_runs: Number of runs for the smooth variants
        eps: noise scaling to be applied on the input image (noise is drawn from N(0,1))
        abs (bool): Flag, if the gradient should be a absolute value
        results_fn: function which is called with the results/ return values. Expected f(grads)

    """
    model.zero_grad()

    if grad_type == "vanilla":
        grad = get_vanilla_image_gradient(model, inpt, err_fn, abs)
    elif grad_type == "guided":
        grad = get_guided_image_gradient(model, inpt, err_fn, abs)
    elif grad_type == "smooth-vanilla":
        grad = get_smooth_image_gradient(model, inpt, err_fn, abs, n_runs, eps, grad_type="vanilla")
    elif grad_type == "smooth-guided":
        grad = get_smooth_image_gradient(model, inpt, err_fn, abs, n_runs, eps, grad_type="guided")
    else:
        warnings.warn("This grad_type is not implemented yet")
        grad = torch.zeros_like(inpt)
    model.zero_grad()

    results_fn(grad)

    return grad

def update_model(original_model, update_dict, exclude_layers=(), do_warnings=True):
    # also allow loading of partially pretrained net
    model_dict = original_model.state_dict()

    # 1. Give warnings for unused update values
    unused = set(update_dict.keys()) - set(exclude_layers) - set(model_dict.keys())
    not_updated = set(model_dict.keys()) - set(exclude_layers) - set(update_dict.keys())
    if do_warnings:
        for item in unused:
            warnings.warn("Update layer {} not used.".format(item))
        for item in not_updated:
            warnings.warn("{} layer not updated.".format(item))

    # 2. filter out unnecessary keys
    update_dict = {k: v for k, v in update_dict.items() if
                   k in model_dict and k not in exclude_layers}

    # 3. overwrite entries in the existing state dict
    model_dict.update(update_dict)

    # 4. load the new state dict
    original_model.load_state_dict(model_dict)


def set_seed(seed):
    """Sets the seed"""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    # if torch.cuda.is_available():
    #     torch.cuda.manual_seed_all(seed)